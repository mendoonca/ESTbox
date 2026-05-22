from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime
import qrcode
import requests
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
BLOB_CERTIFICADOS_CONTAINER = os.environ.get("BLOB_CERTIFICADOS_CONTAINER", "certificados")
REPORT_SERVICE_URL = os.environ.get("REPORT_SERVICE_URL", "http://localhost:8000").rstrip("/")
REPORT_SERVICE_TIMEOUT = int(os.environ.get("REPORT_SERVICE_TIMEOUT", "20"))
DEFAULT_ROLE = "utilizador"
ALLOWED_ROLES = {"admin", "utilizador"}
ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.environ.get("ADMIN_EMAILS", "").split(",")
    if email.strip()
}

# Iniciar a ligação à Base de Dados e escolher a Tabela (Container)
client = CosmosClient(URL, credential=KEY)
database = client.get_database_client("ESTboxDB")
users_container = database.get_container_client("Users") # Para guardar os utilizadores
notificacoes_container = database.get_container_client("Notificacoes") # Para guardar as notificações de inspeção

# Cliente do Blob Storage (opcional para ambiente local sem storage)
blob_service_client = None
blob_container_client = None
blob_certificados_container_client = None
if BLOB_CONNECTION_STRING:
    try:
        blob_service_client = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
        blob_container_client = blob_service_client.get_container_client(BLOB_CONTAINER_NAME)
        if not blob_container_client.exists():
            blob_container_client.create_container()
        blob_certificados_container_client = blob_service_client.get_container_client(BLOB_CERTIFICADOS_CONTAINER)
        if not blob_certificados_container_client.exists():
            blob_certificados_container_client.create_container()
    except Exception:
        blob_service_client = None
        blob_container_client = None
        blob_certificados_container_client = None


def normalize_role(role):
    role_value = (role or "").strip().lower()
    if role_value in ALLOWED_ROLES:
        return role_value
    return DEFAULT_ROLE


def resolve_user_role(email, role):
    if (email or "").strip().lower() in ADMIN_EMAILS:
        return "admin"
    return normalize_role(role)


def get_user_by_email(email):
    query = "SELECT * FROM c WHERE c.email = @email"
    parameters = [{"name": "@email", "value": email}]
    users = list(users_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    if users:
        return users[0]
    return None


def get_owned_vehicle(matricula, user_email):
    query = "SELECT * FROM c WHERE c.id = @matricula AND c.user_email = @user_email"
    parameters = [
        {"name": "@matricula", "value": matricula},
        {"name": "@user_email", "value": user_email}
    ]
    vehicles = list(veiculos_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    return vehicles[0] if vehicles else None


def admin_required(route_function):
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        user_email = session.get('user_email')
        if not user_email:
            flash("Precisas de iniciar sessao para aceder ao painel admin.", "error")
            return redirect(url_for('login'))

        session_role = session.get('user_role')
        if not session_role:
            try:
                user = get_user_by_email(user_email)
            except Exception:
                flash("Nao foi possivel validar a tua permissao de administrador.", "error")
                return redirect(url_for('home'))

            if not user:
                flash("Utilizador nao encontrado.", "error")
                return redirect(url_for('logout'))

            session_role = resolve_user_role(user_email, user.get('role'))
            session['user_role'] = session_role

        if session_role != 'admin':
            flash("Nao tens permissao para aceder ao painel admin.", "error")
            return redirect(url_for('home'))

        return route_function(*args, **kwargs)

    return wrapper

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
            user = get_user_by_email(email)

            if user and check_password_hash(user['password'], password):
                user_role = resolve_user_role(email, user.get('role'))
                session['user_email'] = email
                session['user_role'] = user_role

                if user.get('role') != user_role:
                    user['role'] = user_role
                    users_container.replace_item(item=user['id'], body=user)

                flash("Login efetuado com sucesso!", "success")
                if user_role == 'admin':
                    return redirect(url_for('admin_dashboard'))
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

    return render_template('conta.html', email=user_email, role=session.get('user_role', DEFAULT_ROLE))

@app.route('/logout')
def logout():
    session.pop('user_email', None)
    session.pop('user_role', None)
    flash("Sessao terminada.", "success")
    return redirect(url_for('home'))

@app.route('/registo', methods=['GET', 'POST'])
def registo():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        role = resolve_user_role(email, DEFAULT_ROLE)
        
        # Encriptar a password (Segurança Máxima para o Professor ver!)
        hashed_password = generate_password_hash(password)
        
        user_item = {
            'id': email, # O ID no CosmosDB tem de ser único, o email serve bem
            'email': email,
            'password': hashed_password,
            'role': role
            
            # ----------------- Adicionar mais campos aqui, como nome, data de nascimento, etc. -----------------
        }
        
        try:
            users_container.create_item(body=user_item)
            session['user_email'] = email
            session['user_role'] = role
            flash("Conta criada com sucesso!", "success")
            if role == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('home'))
        except Exception:
            flash("Erro ao criar conta. Verifica se o email ja existe.", "error")
            return redirect(url_for('registo'))

    return render_template('registo.html')


@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    return render_template('indexAdmin.html')

@app.route('/admin/users')
@admin_required
def admin_users():
    users = list(users_container.query_items(
        query="SELECT c.email, c.role FROM c ORDER BY c.email ASC",
        enable_cross_partition_query=True
    ))
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/add', methods=['GET', 'POST'])
@admin_required
def admin_add_user():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password')
        role = normalize_role(request.form.get('role'))

        if not email or not password:
            flash("Preenche o email e a password do utilizador.", "error")
            return redirect(url_for('admin_add_user'))

        if get_user_by_email(email):
            flash("Ja existe um utilizador com esse email.", "error")
            return redirect(url_for('admin_add_user'))

        role = resolve_user_role(email, role)
        hashed_password = generate_password_hash(password)

        user_item = {
            'id': email,
            'email': email,
            'password': hashed_password,
            'role': role
        }

        try:
            users_container.create_item(body=user_item)
            flash("Utilizador criado com sucesso.", "success")
            return redirect(url_for('admin_users'))
        except Exception:
            flash("Erro ao criar o utilizador.", "error")
            return redirect(url_for('admin_add_user'))

    return render_template('admin_add_user.html')

veiculos_container = database.get_container_client("Veiculos")

@app.route('/admin/vehicles')
@admin_required
def admin_vehicles():
    vehicles = list(veiculos_container.query_items(
        query="SELECT * FROM c ORDER BY c.matricula ASC",
        enable_cross_partition_query=True
    ))
    return render_template('admin_vehicles.html', vehicles=vehicles)


def get_vehicle_by_matricula(matricula):
    query = "SELECT * FROM c WHERE c.id = @matricula"
    parameters = [{"name": "@matricula", "value": matricula}]
    vehicles = list(veiculos_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    return vehicles[0] if vehicles else None

@app.route('/admin/users/edit/<email>', methods=['GET', 'POST'])
@admin_required
def admin_edit_user(email):
    user = get_user_by_email(email)
    if not user:
        flash("Utilizador nao encontrado.", "error")
        return redirect(url_for('admin_users'))

    if request.method == 'POST':
        role = normalize_role(request.form.get('role'))
        password = request.form.get('password')

        if password:
            user['password'] = generate_password_hash(password)

        user['role'] = role

        try:
            users_container.replace_item(item=user['id'], body=user)
            flash("Utilizador atualizado com sucesso.", "success")
            return redirect(url_for('admin_users'))
        except Exception:
            flash("Erro ao atualizar o utilizador.", "error")
            return redirect(url_for('admin_edit_user', email=email))

    return render_template('admin_edit_user.html', user=user)

@app.route('/admin/users/delete/<email>', methods=['POST'])
@admin_required
def admin_delete_user(email):
    if email == session.get('user_email'):
        flash("Nao podes remover a conta com a qual estas autenticado.", "error")
        return redirect(url_for('admin_users'))

    user = get_user_by_email(email)
    if not user:
        flash("Utilizador nao encontrado.", "error")
        return redirect(url_for('admin_users'))

    try:
        users_container.delete_item(item=user['id'], partition_key=user['id'])

        associated_vehicles = list(veiculos_container.query_items(
            query="SELECT * FROM c WHERE c.user_email = @user_email",
            parameters=[{"name": "@user_email", "value": email}],
            enable_cross_partition_query=True
        ))
        for vehicle in associated_vehicles:
            veiculos_container.delete_item(item=vehicle['id'], partition_key=vehicle['id'])

        associated_manutencoes = list(manutencoes_container.query_items(
            query="SELECT * FROM c WHERE c.user_email = @user_email",
            parameters=[{"name": "@user_email", "value": email}],
            enable_cross_partition_query=True
        ))
        for manutencao in associated_manutencoes:
            manutencoes_container.delete_item(item=manutencao['id'], partition_key=manutencao['id'])

        flash("Utilizador e dados associados removidos com sucesso.", "success")
    except Exception:
        flash("Erro ao remover o utilizador.", "error")

    return redirect(url_for('admin_users'))

@app.route('/admin/vehicles/edit/<matricula>', methods=['GET', 'POST'])
@admin_required
def admin_edit_vehicle(matricula):
    vehicle = get_vehicle_by_matricula(matricula)
    if not vehicle:
        flash("Veiculo nao encontrado.", "error")
        return redirect(url_for('admin_vehicles'))

    if request.method == 'POST':
        vehicle['marca'] = request.form.get('marca')
        vehicle['modelo'] = request.form.get('modelo')
        vehicle['ano'] = request.form.get('ano')
        vehicle['user_email'] = request.form.get('user_email')

        try:
            veiculos_container.replace_item(item=vehicle['id'], body=vehicle)
            flash("Veiculo atualizado com sucesso.", "success")
            return redirect(url_for('admin_vehicles'))
        except Exception:
            flash("Erro ao atualizar o veiculo.", "error")
            return redirect(url_for('admin_edit_vehicle', matricula=matricula))

    return render_template('admin_edit_vehicle.html', vehicle=vehicle)

@app.route('/admin/vehicles/delete/<matricula>', methods=['POST'])
@admin_required
def admin_delete_vehicle(matricula):
    vehicle = get_vehicle_by_matricula(matricula)
    if not vehicle:
        flash("Veiculo nao encontrado.", "error")
        return redirect(url_for('admin_vehicles'))

    try:
        veiculos_container.delete_item(item=vehicle['id'], partition_key=vehicle['id'])

        associated_manutencoes = list(manutencoes_container.query_items(
            query="SELECT * FROM c WHERE c.matricula = @matricula",
            parameters=[{"name": "@matricula", "value": matricula}],
            enable_cross_partition_query=True
        ))
        for manutencao in associated_manutencoes:
            manutencoes_container.delete_item(item=manutencao['id'], partition_key=manutencao['id'])

        flash("Veiculo e manutencoes associadas removidos com sucesso.", "success")
    except Exception:
        flash("Erro ao remover o veiculo.", "error")

    return redirect(url_for('admin_vehicles'))

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
        'ano': request.form.get('ano'),
        'data_inspecao': request.form.get('data_inspecao')
    }
    
    try:
        veiculos_container.create_item(body=novo_veiculo)
        flash("Veiculo adicionado com sucesso!", "success")
    except Exception:
        flash("Erro ao adicionar veiculo. Verifica se a matricula ja existe.", "error")

    return redirect(url_for('garagem'))


manutencoes_container = database.get_container_client("Manutencoes")


@app.route('/gerar_passaporte/<matricula>', methods=['POST'])
def gerar_passaporte(matricula):
    if 'user_email' not in session:
        flash("Precisas de iniciar sessao para gerar o passaporte digital.", "error")
        return redirect(url_for('login'))

    if not blob_certificados_container_client:
        flash("Blob Storage nao configurado para certificados QR.", "error")
        return redirect(url_for('historico', matricula=matricula))

    user_email = session['user_email']
    matricula_normalizada = (matricula or '').strip().upper()
    veiculo = get_owned_vehicle(matricula_normalizada, user_email)

    if not veiculo:
        flash("Nao tens permissao para gerar o passaporte deste veiculo.", "error")
        return redirect(url_for('garagem'))

    validation_url = f"{request.host_url.rstrip('/')}/validar_veiculo/{matricula_normalizada}"
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(validation_url)
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color='black', back_color='white')

    qr_buffer = BytesIO()
    qr_image.save(qr_buffer, format='PNG')
    qr_buffer.seek(0)

    qr_code_blob_name = f"certificados/{secure_filename(matricula_normalizada)}.png"

    try:
        blob_client = blob_certificados_container_client.get_blob_client(qr_code_blob_name)
        blob_client.upload_blob(
            qr_buffer.getvalue(),
            overwrite=True,
            content_settings=ContentSettings(content_type='image/png')
        )

        veiculo_atualizado = {
            key: value for key, value in veiculo.items() if not key.startswith('_')
        }
        veiculo_atualizado['qr_code_blob_name'] = qr_code_blob_name
        veiculos_container.upsert_item(veiculo_atualizado)
    except Exception:
        flash("Nao foi possivel guardar o QR Code no Blob Storage.", "error")
        return redirect(url_for('historico', matricula=matricula_normalizada))

    flash("Passaporte digital gerado com sucesso.", "success")
    return redirect(url_for('historico', matricula=matricula_normalizada))


@app.route('/qr_code/<matricula>')
def qr_code(matricula):
    if not blob_certificados_container_client:
        flash("Blob Storage nao configurado para certificados QR.", "error")
    matricula_normalizada = (matricula or '').strip().upper()
    veiculo = get_vehicle_by_matricula(matricula_normalizada)

    if not veiculo or not veiculo.get('qr_code_blob_name'):
        flash("Ainda nao existe um QR Code para este veiculo.", "error")
        return redirect(url_for('home'))

    try:
        blob_client = blob_certificados_container_client.get_blob_client(veiculo['qr_code_blob_name'])
        blob_data = blob_client.download_blob().readall()
    except Exception:
        flash("Nao foi possivel carregar o QR Code.", "error")
        return redirect(url_for('home'))

    return send_file(
        BytesIO(blob_data),
        mimetype='image/png',
        as_attachment=False,
        download_name=f"qr_code_{matricula_normalizada}.png"
    )


@app.route('/validar_veiculo/<matricula>')
def validar_veiculo(matricula):
    matricula_normalizada = (matricula or '').strip().upper()
    veiculo = get_vehicle_by_matricula(matricula_normalizada)

    if not veiculo:
        return render_template(
            'validar_veiculo.html',
            matricula=matricula_normalizada,
            veiculo=None,
            qr_valido=False,
            mensagem="Nao foi encontrado nenhum veiculo com esta matricula."
        ), 404

    qr_valido = bool(veiculo.get('qr_code_blob_name'))
    mensagem = (
        "QR Code validado com sucesso."
        if qr_valido
        else "Este veiculo existe, mas ainda nao tem um QR Code associado."
    )

    return render_template(
        'validar_veiculo.html',
        matricula=matricula_normalizada,
        veiculo=veiculo,
        qr_valido=qr_valido,
        mensagem=mensagem
    )

@app.route('/historico/<matricula>')
def historico(matricula):
    if 'user_email' not in session:
        flash("Precisas de iniciar sessao para ver o historico.", "error")
        return redirect(url_for('login'))

    user_email = session['user_email']
    veiculo = get_owned_vehicle((matricula or '').strip().upper(), user_email)

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
    
    return render_template('historico.html', matricula=matricula.upper(), revisoes=lista_revisoes, veiculo=veiculo)


@app.route('/historico/<matricula>/exportar_pdf')
def exportar_historico_pdf(matricula):
    if 'user_email' not in session:
        flash("Precisas de iniciar sessao para exportar o historico.", "error")
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
        flash("Nao tens permissao para exportar este historico.", "error")
        return redirect(url_for('garagem'))

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

    payload = {
        "matricula": matricula,
        "user_email": user_email,
        "revisoes": [
            {
                "data": r.get("data"),
                "descricao": r.get("descricao"),
                "km": r.get("km"),
                "custo": r.get("custo")
            }
            for r in lista_revisoes
        ]
    }

    try:
        response = requests.post(
            f"{REPORT_SERVICE_URL}/reports/vehicle-history",
            json=payload,
            timeout=REPORT_SERVICE_TIMEOUT
        )
        if response.status_code != 200:
            error_detail = (response.text or "").strip()
            if error_detail:
                flash(f"Nao foi possivel gerar o PDF. O servico respondeu {response.status_code}: {error_detail}", "error")
            else:
                flash(f"Nao foi possivel gerar o PDF. O servico respondeu {response.status_code}.", "error")
            return redirect(url_for('historico', matricula=matricula))
    except requests.Timeout as exc:
        flash(f"Timeout ao contactar o servico de relatorios: {exc}", "error")
        return redirect(url_for('historico', matricula=matricula))
    except requests.RequestException as exc:
        flash(f"Servico de relatorios indisponivel. {type(exc).__name__}: {exc}", "error")
        return redirect(url_for('historico', matricula=matricula))

    filename = f"historico_{matricula}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    response = send_file(
        BytesIO(response.content),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

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


@app.context_processor
def inject_notifications():
    user_email = session.get('user_email')
    if user_email:
        query = "SELECT * FROM c WHERE c.user_email = @email AND c.lida = false"
        params = [{"name": "@email", "value": user_email}]
        try:
            notificacoes = list(notificacoes_container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        except CosmosResourceNotFoundError:
            notificacoes = []
        except Exception:
            notificacoes = []
        return dict(notificacoes=notificacoes)
    return dict(notificacoes=[])

#   !! Apenas para testar localmente no nosso computador !!
if __name__ == '__main__':
    app.run(debug=True)