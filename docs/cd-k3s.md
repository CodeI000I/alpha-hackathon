# Деплой в k3s: CI и CD

## Как это устроено

```
push в main
  └─ GitHub Actions (.github/workflows/ci-cd.yaml), облачные раннеры
       1. go vet + go test, сборка фронтенда, helm lint + helm template
       2. docker build → Docker Hub: <user>/alpha-hackaton:<sha> и :latest
       3. коммит в main: image.tag = <sha> в deploy/helm/alpha-hackaton/values.yaml
  └─ Argo CD в k3s
       раз в ~3 минуты сверяет main с кластером, видит новый тег,
       рендерит Helm-чарт и раскатывает server и worker
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
│   └── templates/                  server (Deployment + Service), worker, postgres, rustfs, ingress, configmap
├── argocd/application.yaml         Application для Argo CD: какой чарт и куда раскатывать
└── secrets.example.yaml            шаблон секрета с паролями (настоящий secrets.yaml в .gitignore)
```

Имена объектов в кластере начинаются с имени релиза `alpha`: `alpha` (server), `alpha-worker`, `alpha-postgres`, `alpha-rustfs`, `alpha-config`. Postgres и RustFS можно выключить (`postgres.enabled`, `rustfs.enabled`), если появится внешняя база или S3.

## Что делает workflow

| Job | Когда | Что делает |
|---|---|---|
| `test-and-validate` | push в main, pull request, ручной запуск | `go vet` и `go test` в `backend/`, `npm run build` во `frontend/`, `helm lint --strict`, `helm template`. Отрендеренные манифесты сохраняются артефактом на 7 дней |
| `build-and-push` | только main | Собирает `Dockerfile` из корня и пушит `<DOCKERHUB_USERNAME>/alpha-hackaton:<sha>` и `:latest`. Слои кэшируются в GitHub Actions cache |
| `update-image-tag` | только main, после пуша образа | Прописывает `image.repository` и `image.tag` в `values.yaml` и коммитит в main с `[skip ci]` |

Push, в котором поменялись только `*.md`, `docs/` или `deploy/`, образ не пересобирает: изменения чарта Argo CD подхватывает сам. Pull request проверяется целиком, но образ не собирается.

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

# Пароли: скопировать шаблон, вписать значения (пароль Postgres без @ : / ? #, например openssl rand -hex 24)
cp deploy/secrets.example.yaml deploy/secrets.yaml
kubectl -n alpha apply -f deploy/secrets.yaml
```

`DATABASE_URL` писать не нужно: чарт собирает его из `POSTGRES_PASSWORD` и адреса `alpha-postgres`. Остальные ключи секрета (например, будущий токен Jev) попадут в окружение server и worker как есть.

Если раньше применяли манифесты из старого `deploy/k8s`, удалите их до первой синхронизации: `kubectl -n alpha delete deploy app worker`, `kubectl -n alpha delete sts postgres rustfs`, `kubectl -n alpha delete svc app postgres rustfs`, `kubectl -n alpha delete ingress app`, `kubectl -n alpha delete cm alpha-config`. Тома старой базы (`data-postgres-0`) новый чарт не подхватит, у него свой `data-alpha-postgres-0`.

### 3. Поставить Argo CD

```bash
kubectl create namespace argocd
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

kubectl -n argocd rollout status deploy/argocd-server
```

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

### 5. Домен

В `deploy/helm/alpha-hackaton/values.yaml` заменить `ingress.host: alpha.example.local` на свой домен. Другой вариант: раскомментировать `valuesObject` в `deploy/argocd/application.yaml`, тогда настройка кластера живёт рядом с Application, а не в чарте.

### 6. Запушить код в main и дождаться первой сборки

Этот шаг делает так, что Argo CD есть что раскатывать: чарт появляется на GitHub, а CI собирает первый образ.

```bash
git add -A
git commit -m "CI/CD: Helm chart, Argo CD, GitHub Actions"
git push origin main
```

Дальше GitHub → Actions → CI-CD: должны пройти три job, последняя (`update-image-tag`) сама закоммитит в `main` тег образа. Заберите этот коммит: `git pull --rebase`.

### 7. Подключить приложение к Argo CD

Из корня локальной копии репозитория:

```bash
kubectl apply -f deploy/argocd/application.yaml
```

Argo CD склонирует `main`, отрендерит чарт и создаст объекты в namespace `alpha`. Если применить Application раньше push, ничего страшного: Argo CD покажет ошибку `app path does not exist`, а после push сам всё поднимет. Если раньше первой сборки, поды server и worker повиснут в `ImagePullBackOff` на заглушке `DOCKERHUB_USERNAME/alpha-hackaton`, а после коммита с тегом поднимутся сами.

### 8. Проверить

```bash
kubectl -n argocd get application alpha-hackaton   # SYNC STATUS: Synced, HEALTH STATUS: Healthy
kubectl -n alpha get pods

# UI Argo CD: https://localhost:8080, логин admin
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
kubectl -n argocd port-forward svc/argocd-server 8080:443
```

## Каждый день

* **Выкатить новую версию:** push в main. Через несколько минут после зелёного workflow Argo CD раскатит образ. Что сейчас в кластере: `kubectl -n alpha get deploy alpha -o jsonpath='{.spec.template.spec.containers[0].image}'`.
* **Бот коммитит в main**, поэтому перед своим push делайте `git pull --rebase`.
* **Поменять настройки** (домен, реплики, `JEV_URL`, ресурсы): правка `values.yaml` и push. Образ не пересобирается, Argo CD применит изменения сам. Поды server и worker перезапустятся, если поменялся ConfigMap.
* **Откатиться на прошлый образ:** вписать старый sha в `image.tag` в `values.yaml` и запушить. Сборка не запустится, Argo CD раскатит указанный образ. Откатить код насовсем: `git revert` коммита с кодом, CI соберёт и выкатит новый образ.
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
