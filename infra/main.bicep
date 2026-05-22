// Define a localização (usa a mesma do Resource Group)
param location string = resourceGroup().location

// Cria um nome único para a app para não haver conflitos na internet
param appName string = 'estbox-app-${uniqueString(resourceGroup().id)}'

// Nome único para Storage Account (3-24 chars, minúsculas e números)
param storageAccountName string = 'estboxsa${uniqueString(resourceGroup().id)}'

// Nome do container Blob onde ficam as faturas
param blobContainerName string = 'faturas'

// Nome do container Blob onde ficam os certificados QR
param blobCertificadosContainerName string = 'certificados'

// URL publica do microservico Docker que gera os PDFs de historico
param reportServiceUrl string = ''

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
      linuxFxVersion: 'PYTHON|3.14' // Mantem a versao pedida para a Web App.
    }
  }
}

param functionAppName string = 'estbox-func-${uniqueString(resourceGroup().id)}'

resource functionApp 'Microsoft.Web/sites@2022-09-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.14'
      alwaysOn: true
    }
  }
}


// --- NOVA PARTE: BASE DE DADOS COSMOS DB ---

// Nome único para o CosmosDB (só aceita minúsculas e números)
param cosmosDbName string = 'estbox-db-${uniqueString(resourceGroup().id)}'

// 4. Criar a Conta do CosmosDB (Modo Serverless)
resource cosmosDbAccount 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' = {
  name: cosmosDbName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless' // POUPAR CRÉDITOS!
      }
    ]
  }
}

// 9. Criar Storage Account para guardar as faturas
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource invoicesContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: blobContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource certificadosContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: blobCertificadosContainerName
  properties: {
    publicAccess: 'None'
  }
}

// 5. Criar a Base de Dados (Onde tudo fica guardado)
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-04-15' = {
  parent: cosmosDbAccount
  name: 'ESTboxDB'
  properties: {
    resource: {
      id: 'ESTboxDB'
    }
  }
}

// 6. Criar o Contentor/Tabela para os Utilizadores
resource usersContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'Users'
  properties: {
    resource: {
      id: 'Users'
      partitionKey: {
        paths: [
          '/id'
        ]
        kind: 'Hash'
      }
    }
  }
}

// 7. Criar o Contentor/Tabela para os Veículos
resource veiculosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'Veiculos'
  properties: {
    resource: {
      id: 'Veiculos'
      partitionKey: {
        paths: [
          '/id'
        ]
        kind: 'Hash'
      }
    }
  }
}

// 8. Criar o Contentor/Tabela para as Manutenções
resource manutencoesContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'Manutencoes'
  properties: {
    resource: {
      id: 'Manutencoes'
      partitionKey: {
        paths: [
          '/matricula'
        ]
        kind: 'Hash'
      }
    }
  }
}

resource notificacoesContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'Notificacoes'
  properties: {
    resource: {
      id: 'Notificacoes'
      partitionKey: {
        paths: [ '/user_email' ] // Particionamos pelo email para consultas rápidas
        kind: 'Hash'
      }
    }
  }
}

// 10. Definir variáveis de ambiente da app para Cosmos e Blob
resource webAppAppSettings 'Microsoft.Web/sites/config@2022-09-01' = {
  parent: webApp
  name: 'appsettings'
  properties: {
    COSMOS_URL: cosmosDbAccount.properties.documentEndpoint
    COSMOS_KEY: cosmosDbAccount.listKeys().primaryMasterKey
    BLOB_CONNECTION_STRING: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
    BLOB_CONTAINER_NAME: invoicesContainer.name
    BLOB_CERTIFICADOS_CONTAINER: certificadosContainer.name
    REPORT_SERVICE_URL: reportServiceUrl
    REPORT_SERVICE_TIMEOUT: '20'
  }
}

resource functionAppAppSettings 'Microsoft.Web/sites/config@2022-09-01' = {
  parent: functionApp
  name: 'appsettings'
  properties: {
    COSMOS_URL: cosmosDbAccount.properties.documentEndpoint
    COSMOS_KEY: cosmosDbAccount.listKeys().primaryMasterKey
    AzureWebJobsStorage: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
    FUNCTIONS_EXTENSION_VERSION: '~4'
    FUNCTIONS_WORKER_RUNTIME: 'python'
  }
}

// 11. Mostrar outputs úteis no final
output siteUrl string = 'https://${webApp.properties.defaultHostName}'
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output cosmosEndpoint string = cosmosDbAccount.properties.documentEndpoint
output blobContainer string = invoicesContainer.name
