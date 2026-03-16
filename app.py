from flask import Flask, render_template, request
from azure.cosmos import CosmosClient
import uuid # Usado para gerar um ID único para cada carro
import os

# Inicializa a aplicação
app = Flask(__name__)

# --- CONFIGURAÇÕES DO COSMOS DB ---
# SUBSTITUI ESTES VALORES PELOS QUE ESTÃO NO PORTAL DO AZURE (Passo 1)
URL = os.environ.get("COSMOS_URL")
KEY = os.environ.get("COSMOS_KEY")

# Iniciar a ligação à Base de Dados e escolher a Tabela (Container)
client = CosmosClient(URL, credential=KEY)
database = client.get_database_client("ESTboxDB")
container = database.get_container_client("Veiculos")

# Rota principal (Onde vai estar o formulário)
@app.route('/')
def home():
    # O Python vai à pasta 'templates' e devolve o nosso ficheiro HTML!
    return render_template('index.html')

# Nova rota para receber os dados do formulário e guardar no CosmosDB
@app.route('/adicionar_veiculo', methods=['POST'])
def adicionar_veiculo():
    # 1. Apanhar os dados que o utilizador escreveu no HTML do Martim
    marca = request.form.get('marca')
    modelo = request.form.get('modelo')
    matricula = request.form.get('matricula')
    ano = request.form.get('ano')

    # 2. Criar o documento JSON (O formato que o CosmosDB usa)
    novo_veiculo = {
        "id": str(uuid.uuid4()), # O CosmosDB exige sempre um campo "id" único
        "marca": marca,
        "modelo": modelo,
        "matricula": matricula,
        "ano": ano
    }

    # 3. Guardar na Base de Dados do Azure!
    container.create_item(body=novo_veiculo)

    # 4. Mostrar uma mensagem de sucesso
    return f"<h1>Sucesso!</h1><p>O veículo {marca} {modelo} ({matricula}) foi guardado na base de dados!</p><a href='/'>Voltar</a>"

#   !! Apenas para testar localmente no nosso computador !!
if __name__ == '__main__':
    app.run(debug=True)