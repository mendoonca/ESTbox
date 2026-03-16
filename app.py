from flask import Flask, render_template

# Inicializa a aplicação
app = Flask(__name__)

# Diz ao Python o que fazer quando alguém entra na página principal ("/")
@app.route('/')
def home():
    # O Python vai à pasta 'templates' e devolve o nosso ficheiro HTML!
    return render_template('index.html')

#   !! Apenas para testar localmente no nosso computador !!
if __name__ == '__main__':
    app.run(debug=True)