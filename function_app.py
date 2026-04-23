import azure.functions as func
from azure.cosmos import CosmosClient
from azure.cosmos import PartitionKey
import logging
import os
import datetime
import uuid

app = func.FunctionApp()

# Corre todos os dias as 09:00 (UTC).
@app.timer_trigger(schedule="0 0 9 * * *", arg_name="myTimer", run_on_startup=False)
def verificar_inspecoes(myTimer: func.TimerRequest) -> None:
    logging.info("verificar_inspecoes started")
    client = CosmosClient(os.environ["COSMOS_URL"], credential=os.environ["COSMOS_KEY"])
    database = client.get_database_client("ESTboxDB")
    veiculos_container = database.get_container_client("Veiculos")
    notificacoes_container = database.create_container_if_not_exists(
        id="Notificacoes",
        partition_key=PartitionKey(path="/user_email")
    )
    logging.info("Notificacoes container is ready")

    hoje = datetime.date.today()
    prazo_alerta = hoje + datetime.timedelta(days=30)

    # Procura veículos com inspeção nos próximos 30 dias.
    query = "SELECT * FROM c WHERE c.data_inspecao >= @hoje AND c.data_inspecao <= @limite"
    params = [
        {"name": "@hoje", "value": hoje.isoformat()},
        {"name": "@limite", "value": prazo_alerta.isoformat()}
    ]
    
    veiculos = veiculos_container.query_items(query=query, parameters=params, enable_cross_partition_query=True)
    veiculos = list(veiculos)
    logging.info("verificar_inspecoes found %d vehicles in alert window", len(veiculos))

    for v in veiculos:
        data_inspecao = v.get('data_inspecao')
        if not data_inspecao:
            logging.warning("Skipping vehicle %s without data_inspecao", v.get('matricula', 'unknown'))
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
        logging.info("Notification upserted for vehicle %s with inspection date %s", v.get('matricula', 'unknown'), data_inspecao)

    logging.info("verificar_inspecoes finished")