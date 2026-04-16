from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from azure.cosmos import CosmosClient
from azure.storage.blob import BlobServiceClient, ContentSettings
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import re
import os
import uuid
from io import BytesIO

# Inicializa a aplicação
app = Flask(__name__)
app.secret_key = 'chave_secreta_para_sessões' # Necessário para usar flash messages

# --- CONFIGURAÇÕES DO COSMOS DB ---
URL = os.environ.get("COSMOS_URL")
KEY = os.environ.get("COSMOS_KEY")

# --- CONFIGURAÇÕES DO AZURE BLOB STORAGE ---
BLOB_CONNECTION_STRING = os.environ.get("BLOB_CONNECTION_STRING")
BLOB_CONTAINER_NAME = os.environ.get("BLOB_CONTAINER_NAME", "faturas")

# Iniciar a ligação à Base de Dados e escolher a Tabela (Container)
client = CosmosClient(URL, credential=KEY)
database = client.get_database_client("ESTboxDB")
users_container = database.get_container_client("Users") # Para guardar os utilizadores

# Cliente do Blob Storage (opcional para ambiente local sem storage)
blob_service_client = None
blob_container_client = None
if BLOB_CONNECTION_STRING:
    try:
        blob_service_client = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
        blob_container_client = blob_service_client.get_container_client(BLOB_CONTAINER_NAME)
        if not blob_container_client.exists():
            blob_container_client.create_container()
    except Exception:
        blob_service_client = None
        blob_container_client = None

# Rota principal (Onde vai estar o formulário)
@app.route('/')
def home():
    # O Python vai à pasta 'templates' e devolve o nosso ficheiro HTML!
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            query = "SELECT * FROM c WHERE c.email = @email"
            parameters = [{"name": "@email", "value": email}]
            users = list(users_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))

            if users and check_password_hash(users[0]['password'], password):
                session['user_email'] = email
                flash("Login efetuado com sucesso!", "success")
                return redirect(url_for('home'))

            flash("Email ou password invalidos.", "error")
            return redirect(url_for('login'))
        except Exception:
            flash("Erro ao tentar iniciar sessao.", "error")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/conta')
def conta():
    user_email = session.get('user_email')
    if not user_email:
        flash("Precisas de iniciar sessao para aceder a conta.", "error")
        return redirect(url_for('home'))

    return render_template('conta.html', email=user_email)

@app.route('/logout')
def logout():
    session.pop('user_email', None)
    flash("Sessao terminada.", "success")
    return redirect(url_for('home'))

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
            
            # ----------------- Adicionar mais campos aqui, como nome, data de nascimento, etc. -----------------
        }
        
        try:
            users_container.create_item(body=user_item)
            session['user_email'] = email
            flash("Conta criada com sucesso!", "success")
            return redirect(url_for('home'))
        except Exception:
            flash("Erro ao criar conta. Verifica se o email ja existe.", "error")
            return redirect(url_for('registo'))

    return render_template('registo.html')

veiculos_container = database.get_container_client("Veiculos")

@app.route('/garagem')
def garagem():
    if 'user_email' not in session:
        flash("Precisas de iniciar sessao para ver a garagem.", "error")
        return redirect(url_for('registo'))
    
    # Procurar apenas os veículos deste utilizador
    user_email = session['user_email']
    query = "SELECT * FROM c WHERE c.user_email = @user_email"
    parameters = [{"name": "@user_email", "value": user_email}]
    meus_carros = list(veiculos_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    
    return render_template('garagem.html', carros=meus_carros)

@app.route('/adicionar_veiculo', methods=['POST'])
def adicionar_veiculo():
    if 'user_email' not in session:
        flash("Precisas de iniciar sessao para adicionar um veiculo.", "error")
        return redirect(url_for('registo'))

    matricula = (request.form.get('matricula') or '').strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{6}', matricula):
        flash("A matricula tem de ter exatamente 6 caracteres, em maiusculas, e so pode conter letras e numeros.", "error")
        return redirect(url_for('garagem'))

    novo_veiculo = {
        'id': matricula,
        'user_email': session['user_email'],
        'matricula': matricula,
        'marca': request.form.get('marca'),
        'modelo': request.form.get('modelo'),
        'ano': request.form.get('ano')
    }
    
    try:
        veiculos_container.create_item(body=novo_veiculo)
        flash("Veiculo adicionado com sucesso!", "success")
    except Exception:
        flash("Erro ao adicionar veiculo. Verifica se a matricula ja existe.", "error")

    return redirect(url_for('garagem'))


manutencoes_container = database.get_container_client("Manutencoes")

@app.route('/historico/<matricula>')
def historico(matricula):
    if 'user_email' not in session:
        flash("Precisas de iniciar sessao para ver o historico.", "error")
        return redirect(url_for('login'))

    user_email = session['user_email']
    vehicle_query = "SELECT * FROM c WHERE c.id = @matricula AND c.user_email = @user_email"
    vehicle_parameters = [
        {"name": "@matricula", "value": matricula},
        {"name": "@user_email", "value": user_email}
    ]
    veiculo = list(veiculos_container.query_items(
        query=vehicle_query,
        parameters=vehicle_parameters,
        enable_cross_partition_query=True
    ))

    if not veiculo:
        flash("Nao tens permissao para ver este historico.", "error")
        return redirect(url_for('garagem'))
    
    # Procurar todas as manutenções desta matrícula
    query = "SELECT * FROM c WHERE c.matricula = @matricula AND c.user_email = @user_email ORDER BY c.data DESC"
    parameters = [
        {"name": "@matricula", "value": matricula},
        {"name": "@user_email", "value": user_email}
    ]
    
    lista_revisoes = list(manutencoes_container.query_items(
        query=query, 
        parameters=parameters, 
        enable_cross_partition_query=True
    ))
    
    return render_template('historico.html', matricula=matricula, revisoes=lista_revisoes)


@app.route('/veiculo/<matricula>')
def historico_legado(matricula):
    return redirect(url_for('historico', matricula=matricula))


@app.route('/adicionar_manutencao', methods=['POST'])
def adicionar_manutencao():
    if 'user_email' not in session:
        flash("Precisas de iniciar sessao para registar uma manutencao.", "error")
        return redirect(url_for('login'))

    matricula = (request.form.get('matricula') or '').strip().upper()
    data = (request.form.get('data') or '').strip()
    descricao = (request.form.get('descricao') or '').strip()
    km_raw = (request.form.get('km') or '').strip()
    custo_raw = (request.form.get('custo') or '').strip()
    fatura_file = request.files.get('fatura')

    if not matricula or not data or not descricao or not km_raw:
        flash("Preenche todos os campos obrigatorios da manutencao.", "error")
        return redirect(url_for('historico', matricula=matricula))

    try:
        km = int(km_raw)
        custo = float(custo_raw) if custo_raw else None
    except ValueError:
        flash("KM e custo precisam de valores validos.", "error")
        return redirect(url_for('historico', matricula=matricula))

    vehicle_query = "SELECT * FROM c WHERE c.id = @matricula AND c.user_email = @user_email"
    vehicle_parameters = [
        {"name": "@matricula", "value": matricula},
        {"name": "@user_email", "value": session['user_email']}
    ]
    veiculo = list(veiculos_container.query_items(
        query=vehicle_query,
        parameters=vehicle_parameters,
        enable_cross_partition_query=True
    ))

    if not veiculo:
        flash("Nao tens permissao para adicionar manutencoes a este veiculo.", "error")
        return redirect(url_for('garagem'))

    allowed_mimetypes = {'image/jpeg', 'image/png', 'image/webp'}
    fatura_blob_name = None
    fatura_content_type = None
    fatura_filename = None

    if fatura_file and fatura_file.filename:
        if fatura_file.mimetype not in allowed_mimetypes:
            flash("A fatura tem de ser uma imagem JPG, PNG ou WEBP.", "error")
            return redirect(url_for('historico', matricula=matricula))

        if not blob_container_client:
            flash("Blob Storage nao configurado. Define BLOB_CONNECTION_STRING para guardar faturas.", "error")
            return redirect(url_for('historico', matricula=matricula))

        original_name = secure_filename(fatura_file.filename)
        extension = os.path.splitext(original_name)[1].lower() or '.jpg'
        manutencao_id = uuid.uuid4().hex
        fatura_blob_name = f"{session['user_email']}/{matricula}/{manutencao_id}{extension}"
        fatura_content_type = fatura_file.mimetype
        fatura_filename = original_name

        try:
            blob_client = blob_container_client.get_blob_client(fatura_blob_name)
            blob_client.upload_blob(
                fatura_file.read(),
                overwrite=True,
                content_settings=ContentSettings(content_type=fatura_content_type)
            )
        except Exception:
            flash("Erro ao guardar a foto da fatura no Blob Storage.", "error")
            return redirect(url_for('historico', matricula=matricula))
    else:
        manutencao_id = uuid.uuid4().hex

    nova_manutencao = {
        'id': manutencao_id,
        'user_email': session['user_email'],
        'matricula': matricula,
        'data': data,
        'descricao': descricao,
        'km': km,
        'custo': custo,
        'fatura_blob_name': fatura_blob_name,
        'fatura_content_type': fatura_content_type,
        'fatura_filename': fatura_filename
    }

    try:
        manutencoes_container.create_item(body=nova_manutencao)
        flash("Manutencao registada com sucesso!", "success")
    except Exception:
        flash("Erro ao registar manutencao.", "error")

    return redirect(url_for('historico', matricula=matricula))


@app.route('/fatura/<manutencao_id>')
def ver_fatura(manutencao_id):
    if 'user_email' not in session:
        flash("Precisas de iniciar sessao para ver a fatura.", "error")
        return redirect(url_for('login'))

    query = "SELECT * FROM c WHERE c.id = @id AND c.user_email = @user_email"
    parameters = [
        {"name": "@id", "value": manutencao_id},
        {"name": "@user_email", "value": session['user_email']}
    ]

    manutencoes = list(manutencoes_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))

    if not manutencoes:
        flash("Manutencao nao encontrada.", "error")
        return redirect(url_for('garagem'))

    manutencao = manutencoes[0]
    blob_name = manutencao.get('fatura_blob_name')
    if not blob_name:
        flash("Esta manutencao nao tem fatura anexada.", "error")
        return redirect(url_for('historico', matricula=manutencao.get('matricula', '')))

    if not blob_container_client:
        flash("Blob Storage nao configurado.", "error")
        return redirect(url_for('historico', matricula=manutencao.get('matricula', '')))

    try:
        blob_client = blob_container_client.get_blob_client(blob_name)
        downloaded = blob_client.download_blob().readall()
    except Exception:
        flash("Nao foi possivel obter a fatura.", "error")
        return redirect(url_for('historico', matricula=manutencao.get('matricula', '')))

    content_type = manutencao.get('fatura_content_type') or 'application/octet-stream'
    filename = manutencao.get('fatura_filename') or 'fatura'
    return send_file(BytesIO(downloaded), mimetype=content_type, download_name=filename)

#   !! Apenas para testar localmente no nosso computador !!
if __name__ == '__main__':
    app.run(debug=True)