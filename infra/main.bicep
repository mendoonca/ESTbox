// Define a localização (usa a mesma do Resource Group)
param location string = resourceGroup().location

// Cria um nome único para a app para não haver conflitos na internet
param appName string = 'estbox-app-${uniqueString(resourceGroup().id)}'

// 1. Criar o Plano de Alojamento (O "Computador" no Azure)
resource appServicePlan 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: 'estbox-plan'
  location: location
  sku: {
    name: 'B1' // Usamos o plano B1, que é barato e suficiente para a nossa app de teste
  }
  kind: 'linux'
  properties: {
    reserved: true // Obrigatório para servidores Linux no Azure
  }
}

// 2. Criar a Web App (Onde o nosso código Python/HTML vai correr)
resource webApp 'Microsoft.Web/sites@2022-09-01' = {
  name: appName
  location: location
  properties: {
    serverFarmId: appServicePlan.id
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11' // Configura o servidor automaticamente para Python!
    }
  }
}

// 3. Imprimir o link final do site no terminal quando acabar
output siteUrl string = 'https://${webApp.properties.defaultHostName}'
