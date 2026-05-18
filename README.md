### Comandos Essenciais de Git para a Equipa

* **`git clone <url-do-repositorio>`** - Puxar o projeto do GitHub para o computador pela primeira vez.
* **`git pull`** - Atualizar o código no computador com as últimas alterações feitas (fazer sempre antes de começar a trabalhar).

* **`git add .`** - Preparar todos os ficheiros que foram modificados para serem guardados.
* **`git commit -m "A tua mensagem aqui"`** - Guardar as alterações com uma mensagem a explicar o que foi feito (ex: "Adicionei página de login").
* **`git push`** - Enviar as alterações finais do teu computador para o GitHub (e atualizar o Azure automaticamente).

* **`git log --oneline`** - Ver o histórico de versões (commits) e descobrir o ID de um commit antigo.
* **`git revert <id-do-commit>`** - Desfazer alterações de um commit antigo de forma segura para a equipa.

* **`git reset --hard <id-do-commit>`** - Força o código local a ficar idêntico ao commit escolhido (apaga tudo o que foi feito depois).
* **`git push origin main --force`** - Força o GitHub a aceitar a tua versão antiga, substituindo o histórico lá existente.

### Microserviço Docker de Geração de Relatórios (Azure)

O projeto já inclui um microserviço para gerar PDF do histórico de um veículo:

* **`report_service.py`** - API Flask do relatório (`POST /reports/vehicle-history`).
* **`Dockerfile.report-service`** - imagem Docker preparada para Azure.
* **`requirements-report.txt`** - dependências isoladas deste contentor.

Quando o utilizador clica em **Exportar Histórico em PDF** na página de histórico, o backend principal (`app.py`) chama o microserviço por HTTP e devolve o PDF.

Variáveis de ambiente usadas no backend principal:

* **`REPORT_SERVICE_URL`** - URL do contentor (ex: `https://estbox-reports.<regiao>.azurecontainerapps.io`).
* **`REPORT_SERVICE_TIMEOUT`** - timeout em segundos para a chamada ao microserviço (default `20`).

Exemplo de deploy do contentor no Azure Container Apps:

1. Criar recurso (ou usar existente) para imagem container:
	 * Azure Container Registry (ACR)
2. Build e push da imagem:

```bash
az acr build \
	--registry <nome-acr> \
	--image estbox-report-service:1.0.0 \
	--file Dockerfile.report-service \
	.
```

3. Criar o Azure Container App:

```bash
az containerapp up \
	--name estbox-report-service \
	--resource-group <resource-group> \
	--environment <containerapp-env> \
	--image <nome-acr>.azurecr.io/estbox-report-service:1.0.0 \
	--target-port 8000 \
	--ingress external
```

4. Configurar a Web App com o URL do microserviço:

```bash
az webapp config appsettings set \
	--name <nome-webapp> \
	--resource-group <resource-group> \
	--settings REPORT_SERVICE_URL=https://<url-container-app>
```

Notas:

* O `infra/main.bicep` já suporta `reportServiceUrl` e grava automaticamente `REPORT_SERVICE_URL` nas app settings da Web App.
* Se o microserviço estiver indisponível, a app mostra mensagem de erro ao utilizador e mantém o fluxo sem crash.

### Deploy 100% automático com push

O workflow [main_estbox-app-df4dslxcvqi4c.yml](.github/workflows/main_estbox-app-df4dslxcvqi4c.yml) foi preparado para criar e configurar tudo automaticamente no Azure quando fazes push para `main`:

* Resource Group
* Azure Container Registry (ACR)
* Azure Container Apps Environment
* Container App do microserviço de relatórios (Docker)
* Infra principal via Bicep (Web App, Function App, Cosmos DB, Storage, containers)
* Deploy da app Flask e da Azure Function

Pré-requisitos mínimos no repositório GitHub (Settings > Secrets and variables > Actions):

* `AZURE_CLIENT_ID`
* `AZURE_TENANT_ID`
* `AZURE_SUBSCRIPTION_ID`

Sem estes 3 valores, o workflow não consegue autenticar no Azure para criar recursos.