import ssl

import pika

from config import get_settings

HEARTBEAT = 300

settings = get_settings()


class BasicPikaClient:
    def __init__(self, rabbitmq_broker_id, rabbitmq_user, rabbitmq_password, region):
        # SSL Context for TLS configuration of Amazon MQ for RabbitMQ
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        ssl_context.set_ciphers("ECDHE+AESGCM:!ECDSA")
        if settings.RABBITMQ_SERVER_URL != "":
            url = settings.RABBITMQ_SERVER_URL
            parameters = pika.URLParameters(url)
        else:
            url = f"amqps://{rabbitmq_user}:{rabbitmq_password}@{rabbitmq_broker_id}.mq.{region}.amazonaws.com:5671"
            parameters = pika.URLParameters(url)
            parameters.ssl_options = pika.SSLOptions(context=ssl_context)

        parameters.heartbeat = HEARTBEAT
        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()


class BasicMessageSender(BasicPikaClient):
    def declare_queue(self, queue_name):
        # print(f"Trying to declare queue({queue_name})...")
        self.channel.queue_declare(queue=queue_name)

    def send_message(self, exchange, routing_key, body):
        channel = self.connection.channel()
        channel.basic_publish(exchange=exchange, routing_key=routing_key, body=body)
        # print(
        #     f"Sent message. Exchange: {exchange}, Routing Key: {routing_key}, Body: {body}")

    def close(self):
        self.channel.close()
        self.connection.close()


if __name__ == "__main__":
    # Initialize Basic Message Sender which creates a connection
    # and channel for sending messages.
    broker, username, password, region = (
        "broker",
        "username",
        "password",
        "region",
    )
    basic_message_sender = BasicMessageSender(broker, username, password, region)

    # Declare a queue
    basic_message_sender.declare_queue("hello world queue")

    # Send a message to the queue.
    basic_message_sender.send_message(
        exchange="", routing_key="hello world queue", body=b"Hello World!"
    )

    # Close connections.
    basic_message_sender.close()
