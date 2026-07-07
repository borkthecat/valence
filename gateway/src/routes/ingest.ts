import { Router, Request, Response, NextFunction } from 'express';
import { createEnterpriseIngestAuth } from '../middleware/enterpriseAuth';
import { queuePayload } from '../services/kafkaProducer';
import { parseIngestionPayload } from './ingestSchema';

export const ingestRouter = Router();

ingestRouter.post(
    '/api/v1/ingest',
    createEnterpriseIngestAuth(),
    async (req: Request, res: Response, next: NextFunction): Promise<void> => {
        try {
            const parsed = parseIngestionPayload(req.body);
            await queuePayload(parsed.tenant_id, parsed.batch_id, parsed.profiles);
            res.status(202).json({
                status: 'ACCEPTED',
                batch_id: parsed.batch_id,
                received_records: parsed.profiles.length,
            });
        }
        catch (error) {
            next(error);
        }
    },
);
