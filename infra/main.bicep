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
      linuxFxVersion: 'PYTHON|3.14' // Configura o servidor automaticamente para Python!
    }
  }
}

// 3. Imprimir o link final do site no terminal quando acabar
output siteUrl string = 'https://${webApp.properties.defaultHostName}'


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

// 9. Mostrar o Link da Base de Dados no final
output cosmosEndpoint string = cosmosDbAccount.properties.documentEndpoint
