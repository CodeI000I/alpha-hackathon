# Деплой в k3s: CI и CD

## Как это устроено

```
push в main
  └─ GitHub Actions (.github/workflows/ci-cd.yaml), облачные раннеры
       1. Go race/PG, Python/pgvector, frontend unit/browser, сквозной HTTP smoke
       2. сборка обоих образов, helm lint + helm template
       3. Docker Hub: <user>/alpha-hackaton:<sha> и :analytics-<sha>
       4. коммит обоих тегов в deploy/helm/alpha-hackaton/values.yaml
  └─ Argo CD в k3s
       раз в ~3 минуты сверяет main с кластером, видит новый тег,
       рендерит Helm-чарт и раскатывает Go server/worker и Python API/worker
```

CI ничего не знает о кластере, а кластер сам ходит в GitHub (только исходящие соединения, порт 6443 наружу не открывается) и в Docker Hub за образом.

**Откуда кластер берёт файлы.** На сервер ничего копировать не нужно. В кластер попадают две вещи, и обе он забирает сам:

* **Helm-чарт** (`deploy/helm/alpha-hackaton`). Argo CD клонирует репозиторий с GitHub по deploy key, ветку `main`, и рендерит чарт у себя. Поэтому чарт должен быть запушен в `main`: локальная папка на ноутбуке Argo CD не видна.
* **Код приложения** приходит не файлами, а Docker-образом. Его собирает CI и кладёт в Docker Hub, а k3s скачивает образ по секрету `dockerhub`. Пока CI ни разу не отработал, образа нет.

`deploy/argocd/application.yaml` в кластер тоже не копируется: `kubectl apply -f` читает файл на вашей машине и отправляет в API кластера объект Application, то есть указание Argo CD «следи за этим репозиторием и этой папкой».

## Почему Argo CD, а не раннер GitHub в кластере

| Вариант | Как работает | Плюсы | Минусы |
|---|---|---|---|
| **A. kubeconfig в секретах GitHub** | Облачный раннер ходит в API k3s и делает `helm upgrade` | Ставить в кластер ничего не нужно | API кластера должен быть открыт в интернет, а доступ к кластеру лежит в GitHub |
| **B. Раннер GitHub в кластере (ARC)** | Поды-раннеры в k3s забирают задачи у GitHub и делают `helm upgrade` | Весь пайплайн виден во вкладке Actions | В кластере лежит токен GitHub с правом Administration на репозиторий. Для `helm upgrade` раннеру нужны права почти администратора namespace (Deployment, StatefulSet, Service, Ingress и Secret, в котором Helm хранит релиз) |
| **C. Argo CD (выбран)** | Агент в кластере следит за чартом в git и приводит кластер к нему. CI только пушит образ и коммитит тег | У GitHub нет доступа к кластеру, у кластера только read-only deploy key. Что в git, то и в кластере: откат через git, ручные правки в кластере откатываются. UI с деревом ресурсов хорошо смотрится на демо | Ещё несколько подов в кластере (порядка 0.5–1 ГБ памяти). Бот коммитит тег в main |
| **D. Keel** | Оператор опрашивает Docker Hub и сам обновляет Deployment | Самый простой | Без истории деплоев в git, проект развивается медленно |

Helm-чарт нужен при любом варианте: он заменил манифесты Kustomize и позволяет менять образ, домен, реплики и ресурсы через `values.yaml`.

## Что лежит в репозитории

```
.github/workflows/ci-cd.yaml        пайплайн: тесты → образ в Docker Hub → новый тег в values.yaml
deploy/
├── helm/alpha-hackaton/            Helm-чарт приложения
│   ├── values.yaml                 образ (его обновляет CI), домен, реплики, ресурсы, тома
│   └── templates/                  server (Deployment + Service), worker, postgres, rustfs, ingress + middleware, configmap
├── argocd/application.yaml         Application для Argo CD: какой чарт и куда раскатывать
└── secrets.example.yaml            шаблон секрета с паролями (настоящий secrets.yaml в .gitignore)
```

Имена объектов в кластере начинаются с имени релиза `alpha`: `alpha` (server), `alpha-worker`, `alpha-postgres`, `alpha-rustfs`, `alpha-config`. Postgres и RustFS можно выключить (`postgres.enabled`, `rustfs.enabled`), если появится внешняя база или S3.

## Что делает workflow

| Job | Когда | Что делает |
|---|---|---|
| `pipeline-tests` | push в main, pull request, ручной запуск | Go race и PG; Python и pgvector/checkpoints; frontend unit/Playwright; сквозной Go/Python HTTP smoke с синтетической моделью |
| `test-and-validate` | push в main, pull request, ручной запуск | Go vet/tests, frontend build, сборка `Dockerfile` и `Dockerfile.analytics`, Helm lint/render; manifests сохраняются на 7 дней |
| `build-and-push` | только main, после обеих проверок | Публикует Go/React `:<sha>` и Python `:analytics-<sha>`; также обновляет `latest` и `analytics-latest` |
| `update-image-tag` | main, после публикации обоих образов | Обновляет `image` и `analytics.image` в values одним коммитом с `[skip ci]` |

Push только с `*.md`, `docs/` или `deploy/` не пересобирает образы: чарт Argo CD
подхватывает сам. Pull request собирает оба образа для проверки, без публикации.

В логах Actions имя пользователя Docker Hub замазано как `***`, потому что оно лежит в secrets. Это нормально.

## Настройка, один раз

Нужно: `kubectl` с доступом к кластеру. `helm` нужен только для локальной проверки чарта.

### 1. Docker Hub и GitHub

1. Создать на Docker Hub репозиторий `alpha-hackaton` с видимостью **Private** заранее. Если его нет, первый push создаст репозиторий с видимостью по умолчанию, а на бесплатном аккаунте это Public.
2. Токен для CI: Docker Hub → Account settings → Personal access tokens, право **Read & Write**. В GitHub: Settings → Secrets and variables → Actions → `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (уже есть).
3. Если на `main` включена защита веток с обязательными PR, разрешить GitHub Actions пушить в обход неё, иначе job `update-image-tag` упадёт на `git push`.

### 2. Namespace и секреты приложения

```bash
kubectl create namespace alpha

# Pull из приватного Docker Hub. Отдельный токен с правом Read, не тот, что в CI.
kubectl -n alpha create secret docker-registry dockerhub \
  --docker-username=<dockerhub-user> --docker-password=<dockerhub-read-token>

# Пароли сразу на сервере, без файла (пароль Postgres без @ : / ? #, поэтому hex)
kubectl -n alpha create secret generic alpha-secrets \
  --from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 24)" \
  --from-literal=S3_ACCESS_KEY=alpha-app \
  --from-literal=S3_SECRET_KEY="$(openssl rand -hex 24)" \
  --from-literal=ORCHESTRATOR_TOKEN="$(openssl rand -hex 32)" \
  --from-literal=INTERNAL_API_TOKEN="$(openssl rand -hex 32)"

kubectl -n alpha get secrets   # должны быть dockerhub и alpha-secrets
```

Тот же секрет можно описать файлом: скопировать `deploy/secrets.example.yaml` в `deploy/secrets.yaml` (он в `.gitignore`), вписать значения и `kubectl -n alpha apply -f deploy/secrets.yaml`.

`POSTGRES_PASSWORD` Postgres читает только при первом запуске, когда создаёт базу на пустом томе. Если потом поменять его в секрете, приложение начнёт подключаться с новым паролем, а база будет ждать старый.

Без этих секретов поды server и worker висят в `ImagePullBackOff` с событием `Unable to retrieve some image pull secrets (dockerhub)`, а postgres и rustfs в `CreateContainerConfigError`. Если секреты создали уже после синхронизации, поды можно не ждать, а пересоздать: `kubectl -n alpha delete pods --all`.

`DATABASE_URL` при встроенной PostgreSQL собирается из `POSTGRES_PASSWORD` и
`alpha-postgres`; Python получает тот же DSN явно для своей схемы и чтения Go.
`ORCHESTRATOR_TOKEN` передаётся Python как `AI_SERVICE_TOKEN`. `INTERNAL_API_TOKEN`
обязателен для чтения загруженных файлов воркером. Добавьте `AI_API_KEY` в существующий
Secret для модельных задач; без него сервисы запускаются, чтение работает, анализ
ждёт настройки. Не пересоздавайте пароль PostgreSQL при обновлении уже работающего
окружения. После изменения Secret перезапустите соответствующие deployments.

Перед обновлением проверьте [миграцию email и назначение паролей](../backend/API.md).
Уже существующая БД с PostgreSQL 16 продолжает использовать major 16; образ
`pgvector/pgvector:pg16` добавляет extension. Python init containers применяют
миграции с общим advisory lock. API и worker используют один RWO PVC документов:
одна API-реплика, Recreate и совместное размещение на узле. Увеличивать replicas
до перехода на подходящее общее хранилище чарт не разрешает.

Если раньше применяли манифесты из старого `deploy/k8s`, удалите их до первой синхронизации: `kubectl -n alpha delete deploy app worker`, `kubectl -n alpha delete sts postgres rustfs`, `kubectl -n alpha delete svc app postgres rustfs`, `kubectl -n alpha delete ingress app`, `kubectl -n alpha delete cm alpha-config`. Тома старой базы (`data-postgres-0`) новый чарт не подхватит, у него свой `data-alpha-postgres-0`.

### 3. Поставить Argo CD

```bash
kubectl create namespace argocd
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

kubectl -n argocd rollout status deploy/argocd-server
kubectl -n argocd get pods   # все поды Running
```

Из чего состоит Argo CD:

| Под | За что отвечает |
|---|---|
| `argocd-application-controller` | Главный: сравнивает то, что должно быть по чарту, с тем, что есть в кластере, и создаёт или обновляет объекты в `alpha`. Следит за здоровьем подов |
| `argocd-repo-server` | Клонирует репозиторий во временную папку внутри своего пода, делает `helm template` и отдаёт готовые манифесты контроллеру. На диск сервера ничего не кладёт |
| `argocd-redis` | Кэш манифестов и состояния кластера для остальных компонентов. Без него сверка не работает |
| `argocd-server` | Веб-интерфейс и API для CLI `argocd`. Сам ничего не деплоит |
| `argocd-applicationset-controller` | Генерирует много Application по шаблону (окружения, PR-стенды). Нам не нужен |
| `argocd-notifications-controller` | Уведомления о деплоях в Telegram, Slack и т. п. Нам не нужен |
| `argocd-dex-server` | Вход через GitHub, LDAP и т. п. Нам не нужен, входим под `admin` |

Цепочка: объект Application (шаг 7) → контроллер просит манифесты у repo-server → repo-server клонирует репозиторий по секрету из шага 4 и рендерит чарт → контроллер применяет манифесты в namespace `alpha`.

Если `argocd-redis` висит в `ImagePullBackOff`: Argo CD берёт redis из `public.ecr.aws`, а он бывает недоступен с сервера. Тот же образ есть на Docker Hub:

```bash
kubectl -n argocd describe pod -l app.kubernetes.io/name=argocd-redis | tail -5   # причина ошибки pull
kubectl -n argocd set image deployment/argocd-redis redis=redis:8.2.3-alpine
```

Без redis Argo CD не может сверить приложение (ошибка `ComparisonError ... argocd-redis:6379`), так что это нужно починить до шага 7. Повторный `kubectl apply` манифеста установки вернёт образ из `public.ecr.aws`, команду `set image` тогда нужно повторить.

### 4. Дать Argo CD доступ к приватному репозиторию

Read-only deploy key, только на этот репозиторий:

```bash
ssh-keygen -t ed25519 -N '' -C argocd-alpha -f ~/.ssh/argocd-alpha
```

GitHub → репозиторий → Settings → Deploy keys → Add deploy key: вставить `~/.ssh/argocd-alpha.pub`, галочку **Allow write access** не ставить.

```bash
kubectl -n argocd create secret generic repo-alpha-hackaton \
  --from-literal=type=git \
  --from-literal=url=git@github.com:CodeI000I/alpha-hackaton.git \
  --from-file=sshPrivateKey=$HOME/.ssh/argocd-alpha
kubectl -n argocd label secret repo-alpha-hackaton argocd.argoproj.io/secret-type=repository
```

### 5. Домен и HTTPS

В `deploy/helm/alpha-hackaton/values.yaml`, блок `ingress`:

```yaml
ingress:
  host: alpha.devgit.net
  tls:
    enabled: true
    clusterIssuer: letsencrypt-production   # ClusterIssuer cert-manager, который уже есть в кластере
    secretName: alpha-tls                   # сюда cert-manager положит сертификат
  redirectToHttps: true                     # Traefik Middleware: http → https, 301
```

Чарт сам ставит на Ingress аннотацию `cert-manager.io/cluster-issuer` и блок `tls`, а при `redirectToHttps` создаёт Middleware `alpha-redirect-https` и подключает его аннотацией `traefik.ingress.kubernetes.io/router.middlewares: alpha-alpha-redirect-https@kubernetescrd` (формат `<namespace>-<имя>@kubernetescrd`). Нужны cert-manager с этим ClusterIssuer и DNS-запись домена на IP сервера.

Проверка после синхронизации:

```bash
kubectl -n alpha get certificate          # alpha-tls: READY True
curl -sI http://alpha.devgit.net | head -3  # 301 и Location: https://...
```

Другой вариант для настроек конкретного кластера: раскомментировать `valuesObject` в `deploy/argocd/application.yaml`, тогда они живут рядом с Application, а не в чарте.

### 6. Запушить код в main и дождаться первой сборки

Этот шаг делает так, что Argo CD есть что раскатывать: чарт появляется на GitHub, а CI собирает первый образ.

```bash
git add -A
git commit -m "CI/CD: Helm chart, Argo CD, GitHub Actions"
git push origin main
```

Дальше GitHub → Actions → CI-CD: должны пройти все quality gates, публикация обоих
образов и `update-image-tag`. Бот закоммитит оба тега; заберите коммит `git pull --ff-only`.

### 7. Подключить приложение к Argo CD

Из корня локальной копии репозитория:

```bash
kubectl apply -f deploy/argocd/application.yaml
```

Если `kubectl` настроен только на сервере с k3s, а репозиторий лежит на ноутбуке, скопируйте файл на сервер и примените его там в обычной ssh-сессии:

```bash
scp deploy/argocd/application.yaml <user>@<server>:~/   # на ноутбуке, из папки проекта
ssh <user>@<server>
kubectl apply -f ~/application.yaml                     # уже на сервере
```

Вариант `ssh <server> kubectl apply ...` одной командой часто падает с `permission denied` на `/etc/rancher/k3s/k3s.yaml`: неинтерактивный ssh не читает `~/.bashrc`, где обычно задан `KUBECONFIG`, и kubectl идёт в root-only конфиг k3s.

Argo CD склонирует `main`, отрендерит чарт и создаст объекты в namespace `alpha`. Если применить Application раньше push, ничего страшного: Argo CD покажет ошибку `app path does not exist`, а после push сам всё поднимет. Если раньше первой сборки, поды server и worker повиснут в `ImagePullBackOff` на заглушке `DOCKERHUB_USERNAME/alpha-hackaton`, а после коммита с тегом поднимутся сами.

### 8. Проверить

```bash
kubectl -n argocd get application alpha-hackaton   # SYNC STATUS: Synced, HEALTH STATUS: Healthy
kubectl -n alpha get pods

# UI Argo CD: https://localhost:8080, логин admin
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
kubectl -n argocd port-forward svc/argocd-server 8080:443
```

Argo CD не копирует репозиторий на диск сервера: он клонирует его во временный каталог внутри пода `argocd-repo-server`, рендерит чарт и создаёт объекты. Результат виден как поды в namespace `alpha`, а не как файлы.

Если в `alpha` пусто или приложение не `Synced`:

```bash
kubectl -n argocd get application alpha-hackaton -o jsonpath='{.status.sync.status} {.status.health.status}{"\n"}{.status.conditions}{"\n"}'
kubectl -n argocd get secret -l argocd.argoproj.io/secret-type=repository   # секрет репозитория есть
kubectl -n argocd logs deploy/argocd-repo-server --tail=50                  # ошибки клонирования и рендера
kubectl -n argocd logs statefulset/argocd-application-controller --tail=50  # ошибки синхронизации
```

Частые причины: Application не создан (`kubectl -n argocd get applications` пустой, см. шаг 7); не работает `argocd-redis` (см. шаг 3); `url` в секрете репозитория не совпадает с `repoURL` в Application буква в букву (`git@github.com:CodeI000I/alpha-hackaton.git`); deploy key не добавлен в репозиторий; в `alpha` нет секретов `dockerhub` и `alpha-secrets` из шага 2 (поды в `ImagePullBackOff` или `CreateContainerConfigError`).

## Каждый день

* **Выкатить новую версию:** push в main. Через несколько минут после зелёного workflow Argo CD раскатит образ. Что сейчас в кластере: `kubectl -n alpha get deploy alpha -o jsonpath='{.spec.template.spec.containers[0].image}'`.
* **Бот коммитит в main**, поэтому перед своим push делайте `git pull --rebase`.
* **Поменять настройки** (домен, `ORCHESTRATOR_URL`, ресурсы): правка `values.yaml` и push. Образы не пересобираются, ConfigMap меняет checksum и перезапускает процессы.
* **Откатить приложение:** вписать совместимые прежние `image.tag` и `analytics.image.tag` в values и запушить. Сборка не запустится. Миграции additive; код должен быть совместим с текущей схемой. Перед откатом сохраняйте backup БД и файлов.
* **Не ждать опроса:** в UI Argo CD кнопка Refresh, или `kubectl -n argocd annotate application alpha-hackaton argocd.argoproj.io/refresh=normal --overwrite`.
* **Ручные правки в кластере** (`kubectl edit`, `kubectl scale`) Argo CD откатит из-за `selfHeal`. Меняйте `values.yaml`.

## Проверить чарт локально

```bash
make chart
# без установленного helm:
docker run --rm -v "$PWD:/apps" -w /apps alpine/helm:3.19.0 lint deploy/helm/alpha-hackaton --strict
docker run --rm -v "$PWD:/apps" -w /apps alpine/helm:3.19.0 template alpha deploy/helm/alpha-hackaton -n alpha
```

## Если всё же нужен раннер в кластере (ARC)

Подробная установка ARC (контроллер, токен, RBAC, набор раннеров `alpha-k3s`) есть в истории git: коммит `4228d7d`, файлы `deploy/ci/` и прошлая версия этого документа. Отличия от той схемы:

* job `update-image-tag` заменить на job с `runs-on: alpha-k3s`, который делает
  `helm upgrade --install alpha deploy/helm/alpha-hackaton -n alpha --set image.repository="$IMAGE_NAME" --set-string image.tag="$IMAGE_TAG" --wait --timeout 5m`;
* узкой роли из `deployer-rbac.yaml` для Helm мало, нужна роль администратора namespace:
  `kubectl create rolebinding deployer-admin -n alpha --clusterrole=admin --serviceaccount=arc-runners:deployer`;
* убрать `deploy/**` из `paths-ignore`, иначе изменения чарта не будут доезжать до кластера.
