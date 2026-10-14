# Деплой в k3s: варианты и инструкция

## Какие есть варианты

| Вариант | Как работает | Плюсы | Минусы |
|---|---|---|---|
| **A. kubeconfig в секретах GitHub** | Раннер GitHub в облаке ходит в API k3s и делает `kubectl set image` | Ставить в кластер ничего не нужно | API кластера (порт 6443) должен быть открыт в интернет, а в GitHub лежит доступ к кластеру. Для домашнего или учебного кластера не подходит |
| **B. Раннер GitHub внутри кластера (ARC)** | Actions Runner Controller запускает поды-раннеры в k3s. Они сами забирают задачи у GitHub (только исходящие соединения) и деплоят через ServiceAccount с узкими правами | Кластер не торчит наружу; весь пайплайн в одном workflow и его видно во вкладке Actions; просто отлаживать | Нужен токен GitHub в кластере; раннер с правами в кластере выполняет код из репозитория, поэтому годится только для приватного репозитория |
| **C. GitOps (Argo CD или Flux)** | Агент в кластере следит за git-репозиторием (и за Docker Hub) и сам приводит кластер к описанному состоянию | Кластер не торчит наружу; откат через git; у Argo CD есть UI, который хорошо смотрится на демо | Больше движущихся частей; для автообновления образа нужен Argo CD Image Updater или Flux image automation, который коммитит новый тег в репозиторий |
| **D. Keel** | Небольшой оператор в кластере опрашивает Docker Hub и сам обновляет Deployment, когда появляется новый тег (по аннотации на Deployment) | Самый простой вариант: CI только пушит образ, в кластере один под | Работает по тегам вроде `latest` или semver, истории деплоев и отката через git нет; проект развивается медленно |

**Рекомендую B (ARC)** на время хакатона: это ровно «агент GitHub в кластере», один workflow делает build → push → deploy, а прав у агента ровно столько, чтобы поменять образ в двух Deployment. Если после хакатона проект будет жить дальше, стоит перейти на C (Argo CD): манифесты и версии тогда целиком описаны в git.

Сборку образа лучше оставить на облачном раннере GitHub (`ubuntu-latest`), а раннеру в кластере отдать только деплой. Тогда в k3s не нужен Docker-in-Docker и привилегированные поды.

## Инструкция: ARC в k3s

Нужно: `kubectl` с доступом к кластеру, `helm` 3.8+, приватный репозиторий на GitHub, приватный репозиторий на Docker Hub. Файлы, на которые ссылается инструкция, лежат в `deploy/`.

### 1. Развернуть приложение один раз вручную

```bash
kubectl apply -f deploy/k8s/namespace.yaml

# Секрет для pull из приватного Docker Hub (Access Token: Docker Hub → Account settings → Personal access tokens, право Read)
kubectl -n alpha create secret docker-registry dockerhub \
  --docker-username=<dockerhub-user> --docker-password=<dockerhub-token>

# Пароли приложения: скопировать secrets.example.yaml → secrets.yaml, вписать значения, не коммитить
kubectl -n alpha apply -f deploy/k8s/secrets.yaml

# В deploy/k8s/kustomization.yaml заменить DOCKERHUB_USER, затем:
kubectl apply -k deploy/k8s
```

### 2. Поставить контроллер ARC

```bash
helm install arc \
  --namespace arc-systems --create-namespace \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller

kubectl -n arc-systems get pods   # должен быть Running под arc-gha-rs-controller-...
```

### 3. Дать раннеру доступ к GitHub

Самое простое на хакатоне: fine-grained personal access token.

1. GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token.
2. Repository access: только `alpha-hackaton`.
3. Permissions → Repository → **Administration: Read and write** (нужно, чтобы регистрировать раннеры уровня репозитория).

```bash
kubectl create namespace arc-runners
kubectl -n arc-runners create secret generic github-arc --from-literal=github_token=<token>
```

На будущее надёжнее GitHub App вместо личного токена. Тогда в секрет кладутся `github_app_id`, `github_app_installation_id` и `github_app_private_key`.

### 4. Выдать раннеру права в кластере

```bash
kubectl apply -f deploy/ci/deployer-rbac.yaml
```

Это ServiceAccount `deployer` в `arc-runners`, которому в namespace `alpha` разрешено только читать и патчить Deployment и смотреть поды. Ни секретов, ни других namespace он не видит.

### 5. Поставить набор раннеров

В `deploy/ci/arc-values.yaml` заменить `OWNER` на владельца репозитория, затем:

```bash
helm install alpha-k3s \
  --namespace arc-runners \
  -f deploy/ci/arc-values.yaml \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
```

Имя релиза `alpha-k3s` — это метка, по которой workflow выбирает раннер (`runs-on: alpha-k3s`). Проверка: в репозитории Settings → Actions → Runners появится scale set `alpha-k3s`. При `minRunners: 0` поды создаются только на время задачи.

### 6. Workflow

Пример лежит в `deploy/ci/deploy.workflow.example.yml`. Когда дойдём до Actions, его нужно скопировать в `.github/workflows/deploy.yml` и в настройках репозитория добавить:

* Variables: `DOCKERHUB_USER`
* Secrets: `DOCKERHUB_TOKEN` (токен Docker Hub с правом Read & Write)

Job `build` собирает и пушит образ с тегом `sha` коммита на облачном раннере. Job `deploy` на раннере в кластере делает `kubectl set image` для `app` и `worker` и ждёт `rollout status`. Если раскатка не прошла, job падает, а откат делается так:

```bash
kubectl -n alpha rollout undo deployment/app
```

### Проверка без GitHub

```bash
kubectl -n arc-runners run kubectl-test --rm -it --restart=Never \
  --image=bitnami/kubectl --overrides='{"spec":{"serviceAccountName":"deployer"}}' \
  -- get deploy -n alpha
```

Команда должна вывести `app` и `worker`. Если попросить её о `get secrets -n alpha`, она должна вернуть `Forbidden`.

## Если выберете GitOps (вариант C)

Кратко, для сравнения:

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

Дальше создаётся `Application`, который смотрит на `deploy/k8s` в репозитории (Argo CD умеет kustomize), и добавляется Argo CD Image Updater. Он следит за тегами в Docker Hub и коммитит новый тег в `kustomization.yaml`. CI тогда только собирает и пушит образ, а в кластер никто снаружи не ходит.
