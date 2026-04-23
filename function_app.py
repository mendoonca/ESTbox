import azure.functions as func
from azure.cosmos import CosmosClient
import os
import datetime
import uuid

app = func.FunctionApp()

#                 !!!!!!!!!!!!  Corre todos os dias às 09:00   !!!!!!!!!!!!
@app.timer_trigger(schedule="0 0 3 * * *", arg_name="myTimer", run_on_startup=False)
def verificar_inspecoes(myTimer: func.TimerRequest) -> None:
    client = CosmosClient(os.environ["COSMOS_URL"], credential=os.environ["COSMOS_KEY"])
    database = client.get_database_client("ESTboxDB")
    veiculos_container = database.get_container_client("Veiculos")
    notificacoes_container = database.get_container_client("Notificacoes")

    hoje = datetime.date.today()
    prazo_alerta = hoje + datetime.timedelta(days=30)

    # Procura veículos com inspeção nos próximos 30 dias.
    query = "SELECT * FROM c WHERE c.data_inspecao >= @hoje AND c.data_inspecao <= @limite"
    params = [
        {"name": "@hoje", "value": hoje.isoformat()},
        {"name": "@limite", "value": prazo_alerta.isoformat()}
    ]
    
    veiculos = veiculos_container.query_items(query=query, parameters=params, enable_cross_partition_query=True)

    for v in veiculos:
        data_inspecao = v.get('data_inspecao')
        if not data_inspecao:
            continue

        notificacao_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{v.get('user_email', '')}|{v.get('matricula', '')}|{data_inspecao}"
        ).hex

        nova_notificacao = {
            'id': notificacao_id,
            'user_email': v['user_email'],
            'matricula': v.get('matricula'),
            'data_inspecao': data_inspecao,
            'tipo': 'inspecao',
            'mensagem': f"Alerta: O seu veículo {v['marca']} ({v['matricula']}) tem a próxima inspeção marcada para {v['data_inspecao']}.",
            'lida': False,
            'data_criacao': datetime.date.today().isoformat()
        }

        notificacoes_container.upsert_item(body=nova_notificacao)