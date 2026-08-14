import 'dotenv/config';
import express from 'express';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { scrapeJobs } from './lib/apify.js';
import { extractSearchParams, scoreJobs, MODEL_ID } from './lib/llm.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 3000;

const MIN_LIMIT = 10;
const MAX_LIMIT = 30;

app.use(express.json({ limit: '1mb' }));
app.use(express.static(join(__dirname, 'public')));

app.post('/api/search', async (req, res) => {
    const { jobDescription, limit, source = 'both', useAi = true } = req.body || {};

    if (!jobDescription || jobDescription.trim().length < 20) {
        return res.status(400).json({ error: 'Job description kam se kam 20 characters ka hona chahiye' });
    }

    const apifyToken = process.env.APIFY_API_KEY;
    const openRouterKey = process.env.OPENROUTER_API_KEY;
    if (!apifyToken) return res.status(500).json({ error: 'APIFY_API_KEY .env me nahi mila' });
    if (useAi && !openRouterKey) return res.status(500).json({ error: 'OPENROUTER_API_KEY .env me nahi mila' });

    const cappedLimit = Math.min(MAX_LIMIT, Math.max(MIN_LIMIT, Number(limit) || MIN_LIMIT));

    // NDJSON stream: har line ek event, taaki UI live progress dikha sake.
    res.setHeader('Content-Type', 'application/x-ndjson');
    res.setHeader('Cache-Control', 'no-cache');
    const send = (event) => res.write(`${JSON.stringify(event)}\n`);
    const progress = (stage, message, isError = false) => send({ type: 'progress', stage, message, isError });

    try {
        let params = { title: null, location: 'India', country: 'IN', summary: '', mustHaveSkills: [] };

        if (useAi) {
            progress('parse', `${MODEL_ID} job description padh raha hai...`);
            const extracted = await extractSearchParams(jobDescription, openRouterKey);
            params = extracted.params;
            progress('parse', `Search banaya: "${params.title}" in ${params.location} (${params.country})`);
        } else {
            // AI off ho to JD ki pehli line ko hi search keyword maan lete hain.
            params.title = jobDescription.trim().split('\n')[0].slice(0, 60);
            progress('parse', `AI off — keyword: "${params.title}"`);
        }

        send({ type: 'params', params, limit: cappedLimit });

        progress('scrape', `Apify chal raha hai (max ${cappedLimit} jobs per source)...`);
        let jobs = await scrapeJobs({
            title: params.title,
            location: params.location,
            country: params.country,
            limit: cappedLimit,
            source,
            token: apifyToken,
        }, progress);

        progress('scrape', `Total ${jobs.length} unique jobs mile`);

        let usage = null;
        if (useAi && jobs.length) {
            progress('score', `${jobs.length} jobs ko JD ke against match kar raha hoon...`);
            const scored = await scoreJobs(jobDescription, jobs, openRouterKey, {}, progress);
            jobs = scored.jobs;
            usage = scored.usage;
            // Best match sabse upar.
            jobs.sort((a, b) => (b.matchScore ?? -1) - (a.matchScore ?? -1));
        }

        send({ type: 'done', jobs, params, usage, model: MODEL_ID });
    } catch (err) {
        send({ type: 'error', message: err.message });
    } finally {
        res.end();
    }
});

app.listen(PORT, () => {
    console.log(`\n  Hiring Agent chal raha hai:  http://localhost:${PORT}\n`);
});
