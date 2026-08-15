const MODEL = 'deepseek/deepseek-v4-pro';
const API_URL = 'https://openrouter.ai/api/v1/chat/completions';

async function chat(messages, { apiKey, temperature = 0.2 }) {
    const res = await fetch(API_URL, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${apiKey}`,
            'Content-Type': 'application/json',
            'X-Title': 'Hiring Agent',
        },
        body: JSON.stringify({
            model: MODEL,
            messages,
            temperature,
            response_format: { type: 'json_object' },
        }),
    });

    if (!res.ok) {
        throw new Error(`OpenRouter ${res.status}: ${(await res.text()).slice(0, 300)}`);
    }

    const data = await res.json();
    const content = data.choices?.[0]?.message?.content;
    if (!content) throw new Error('OpenRouter ne khaali response bheja');

    // Model kabhi kabhi JSON ko ```json fence me wrap kar deta hai.
    const cleaned = content.trim().replace(/^```(?:json)?\s*/i, '').replace(/```$/, '');
    return { json: JSON.parse(cleaned), usage: data.usage };
}

const EXTRACT_PROMPT = `You are a recruitment search assistant. Read the job description and extract search parameters for scraping LinkedIn and Indeed.

Return ONLY a JSON object with these keys:
- "title": the most effective short search keyword string (2-5 words) for a job board. Use the common market job title, not the company's fancy internal title.
- "location": city or region name as typed on a job board. If the JD is remote or has no location, use the country name.
- "country": ISO 3166-1 alpha-2 country code (e.g. "IN", "US", "GB"). Default "IN" if truly unclear.
- "seniority": one of "internship", "entry", "mid", "senior", "lead", "unknown".
- "mustHaveSkills": array of up to 8 key technical skills mentioned.
- "summary": one short sentence describing what role is being searched for.`;

export async function extractSearchParams(jobDescription, apiKey) {
    const { json, usage } = await chat([
        { role: 'system', content: EXTRACT_PROMPT },
        { role: 'user', content: jobDescription },
    ], { apiKey });

    return {
        params: {
            title: json.title || 'Software Engineer',
            location: json.location || 'India',
            country: (json.country || 'IN').toUpperCase().slice(0, 2),
            seniority: json.seniority || 'unknown',
            mustHaveSkills: Array.isArray(json.mustHaveSkills) ? json.mustHaveSkills : [],
            summary: json.summary || '',
        },
        usage,
    };
}

const SCORE_PROMPT = `You are a recruitment matching engine. You get a target job description and a numbered list of scraped job postings.

For EACH posting, judge how well it matches the target job description.

Return ONLY a JSON object of the form:
{"results": [{"i": <the posting number>, "score": <integer 0-100>, "reason": "<max 12 words explaining the score>"}]}

Scoring guide: 90+ near-identical role and seniority; 70-89 strong match with minor gaps; 50-69 related but different seniority/stack; below 50 weak match.
You MUST return one entry for every posting number given.`;

// Poore descriptions bhejne se tokens bahut lagte hain, isliye trim karke chhote batches me bhejte hain.
function compactJob(job, index) {
    return [
        `#${index}`,
        `Title: ${job.title || '-'}`,
        `Company: ${job.company || '-'}`,
        `Location: ${job.location || '-'}`,
        `Type: ${job.contractType || '-'} | Level: ${job.experienceLevel || '-'}`,
        `Description: ${(job.description || '').replace(/\s+/g, ' ').slice(0, 700)}`,
    ].join('\n');
}

/**
 * Jobs ko batches me score karta hai taaki ek hi request bahut badi na ho jaye.
 */
export async function scoreJobs(jobDescription, jobs, apiKey, { batchSize = 15 } = {}, onProgress = () => {}) {
    const scores = new Map();
    const batches = [];
    for (let i = 0; i < jobs.length; i += batchSize) batches.push(jobs.slice(i, i + batchSize));

    let done = 0;
    const totalUsage = { prompt_tokens: 0, completion_tokens: 0 };

    // Sabhi batches parallel me — har batch apne indexes ke saath.
    await Promise.all(batches.map(async (batch, batchNo) => {
        const offset = batchNo * batchSize;
        const listing = batch.map((job, k) => compactJob(job, offset + k)).join('\n\n');

        try {
            const { json, usage } = await chat([
                { role: 'system', content: SCORE_PROMPT },
                { role: 'user', content: `TARGET JOB DESCRIPTION:\n${jobDescription.slice(0, 6000)}\n\n---\n\nPOSTINGS:\n${listing}` },
            ], { apiKey });

            for (const r of json.results || []) {
                if (typeof r.i === 'number') {
                    scores.set(r.i, { score: Number(r.score) || 0, reason: r.reason || '' });
                }
            }
            totalUsage.prompt_tokens += usage?.prompt_tokens || 0;
            totalUsage.completion_tokens += usage?.completion_tokens || 0;
        } catch (err) {
            onProgress('score', `Batch ${batchNo + 1} could not be scored: ${err.message}`, true);
        }

        done += 1;
        onProgress('score', `AI matching: ${done}/${batches.length} batches done`);
    }));

    return {
        jobs: jobs.map((job, i) => ({
            ...job,
            matchScore: scores.get(i)?.score ?? null,
            matchReason: scores.get(i)?.reason ?? null,
        })),
        usage: totalUsage,
    };
}

export const MODEL_ID = MODEL;
