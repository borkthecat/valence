import { Kafka, Producer, logLevel } from 'kafkajs';
import { environment } from '../config/environment';

export type QueuedProfile = Readonly<Record<string, unknown>>;

let producer: Producer | null = null;

function brokers(): string[] {
    return environment.KAFKA_BOOTSTRAP_SERVERS.split(',')
        .map((broker) => broker.trim())
        .filter((broker) => broker.length > 0);
}

async function getProducer(): Promise<Producer> {
    if (producer === null) {
        const kafka = new Kafka({
            clientId: 'valence-gateway-producer',
            brokers: brokers(),
            logLevel: logLevel.NOTHING,
        });
        producer = kafka.producer({
            allowAutoTopicCreation: false,
            transactionTimeout: 30000,
        });
        await producer.connect();
    }
    return producer;
}

export async function queuePayload(
    tenantId: string,
    batchId: string,
    profiles: readonly QueuedProfile[],
): Promise<void> {
    const client = await getProducer();
    await client.send({
        topic: environment.KAFKA_INGEST_TOPIC,
        acks: -1,
        messages: profiles.map((profile) => ({
            key: tenantId,
            value: JSON.stringify({
                batch_id: batchId,
                tenant_id: tenantId,
                data: profile,
            }),
        })),
    });
}

export async function disconnectProducer(): Promise<void> {
    if (producer !== null) {
        await producer.disconnect();
        producer = null;
    }
}
