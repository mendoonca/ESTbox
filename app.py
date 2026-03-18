from flask import Flask, render_template, request, redirect, url_for, flash
from azure.cosmos import CosmosClient, PartitionKey
from werkzeug.security import generate_password_hash, check_password_hash
import uuid # Usado para gerar um ID único para cada carro
import os

# Inicializa a aplicação
app = Flask(__name__)
app.secret_key = 'chave_secreta_para_sessões' # Necessário para usar flash messages

# --- CONFIGURAÇÕES DO COSMOS DB ---
# SUBSTITUI ESTES VALORES PELOS QUE ESTÃO NO PORTAL DO AZURE (Passo 1)
URL = os.environ.get("COSMOS_URL")
KEY = os.environ.get("COSMOS_KEY")

# Iniciar a ligação à Base de Dados e escolher a Tabela (Container)
client = CosmosClient(URL, credential=KEY)
database = client.get_database_client("ESTboxDB")
container = database.get_container_client("Veiculos")
users_container = database.get_container_client("Users") # Para guardar os utilizadores

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

@app.route('/registo', methods=['GET', 'POST'])
def registo():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Encriptar a password (Segurança Máxima para o Professor ver!)
        hashed_password = generate_password_hash(password)
        
        user_item = {
            'id': email, # O ID no CosmosDB tem de ser único, o email serve bem
            'email': email,
            'password': hashed_password
        }
        
        try:
            users_container.create_item(body=user_item)
            flash("Conta criada com sucesso!", "success")
            return redirect(url_for('home'))
        except Exception as e:
            flash("Erro ao criar conta. Verifica se o email ja existe.", "error")
            return redirect(url_for('registo'))

    return render_template('registo.html')

#   !! Apenas para testar localmente no nosso computador !!
if __name__ == '__main__':
    app.run(debug=True)