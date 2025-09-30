from prometheus_client import Counter, Gauge, generate_latest


ACTIVE_CLIENTS = Gauge('active_clients', 'Number of active clients')
ACTIVE_SENSORS = Gauge('active_sensors', 'Number of active sensors')
SENSOR_MESSAGES = Counter('sensor_messages_total', 'Sensor messages', ['sensor_id'])

def get_metrics():
    return generate_latest()