import json
import os
from dotenv import load_dotenv
from kafka import KafkaProducer
from kafka.errors import KafkaTimeoutError

from ..utils.temp_db import list_active_jobs

load_dotenv()

agent_name = os.getenv('AGENT_NAME')
kafka_brokers = os.getenv('KAFKA_BROKERS')
topic_name = os.getenv('KAFKA_TOPIC')


def write_to_kafka(data, status):
    """
    Send a status update for the current execution to Kafka.
    Looks up the taskId by matching this process’s PID in active jobs.
    """
    producer = None
    try:
        producer = KafkaProducer(bootstrap_servers=kafka_brokers)
        current_pid = os.getpid()

        # Look for the job that matches the current PID
        jobs = list_active_jobs()
        task_execution_id = next((j.get('id') for j in jobs if j.get('pid') == current_pid), 'NA')

        message = {
            'agent': agent_name,
            'data': data,
            'taskId': task_execution_id,
            'status': status
        }

        payload = json.dumps(message).encode('utf-8')
        ack = producer.send(topic_name, value=payload)
        return ack.get()

    except KafkaTimeoutError:
        error_msg = f"Timeout error sending data to Kafka topic {topic_name}"
        print(error_msg)
        raise
    except Exception as e:
        error_msg = f"Error sending data to Kafka topic {topic_name}: {e}"
        print(error_msg)
        raise
    finally:
        if producer is not None:
            producer.close()
