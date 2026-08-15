import { ApifyClient } from 'apify-client';

// bebity/linkedin-jobs-scraper ke liye paid rental chahiye; ye pay-per-event actor free plan par chalta hai.
const LINKEDIN_ACTOR = 'curious_coder/linkedin-jobs-scraper';
const INDEED_ACTOR = 'misceres/indeed-scraper';

// Har actor ka output shape alag hai, isliye ek common shape me normalize kar rahe hain.
function normalizeLinkedIn(job) {
    return {
        source: 'linkedin',
        title: job.title ?? null,
        company: job.companyName ?? null,
        location: job.location ?? null,
        postedAt: job.postedAt ?? job.publishedAt ?? null,
        contractType: job.employmentType || null,
        experienceLevel: job.seniorityLevel || null,
        workType: job.workplaceType || null,
        salary: job.salary || null,
        url: job.link ?? job.jobUrl ?? null,
        applyUrl: job.applyUrl || null,
        applicants: job.applicantsCount || null,
        description: job.descriptionText ?? job.description ?? null,
    };
}

function normalizeIndeed(job) {
    return {
        source: 'indeed',
        title: job.positionName ?? null,
        company: job.company ?? null,
        location: job.location ?? null,
        postedAt: job.postedAt ?? job.postingDateParsed ?? null,
        contractType: Array.isArray(job.jobType) ? job.jobType.join(', ') : (job.jobType ?? null),
        experienceLevel: null,
        workType: job.isRemote ? 'Remote' : null,
        salary: job.salary ?? null,
        url: job.url ?? null,
        applyUrl: job.externalApplyLink ?? null,
        applicants: null,
        description: job.description ?? null,
    };
}

/**
 * Dono job boards ko parallel me scrape karta hai.
 * onProgress(stage, message) se caller ko live updates milte hain.
 */
export async function scrapeJobs({ title, location, country, limit, source = 'both', token }, onProgress = () => {}) {
    const client = new ApifyClient({ token });

    const runOne = async (actorId, input, label, normalize) => {
        onProgress(label, `Starting the ${label} scraper...`);
        try {
            const run = await client.actor(actorId).call(input);
            const { items } = await client.dataset(run.defaultDatasetId).listItems();
            onProgress(label, `Got ${items.length} jobs from ${label}`);
            return items.map(normalize);
        } catch (err) {
            onProgress(label, `${label} failed: ${err.message}`, true);
            return [];
        }
    };

    const tasks = [];

    if (source === 'both' || source === 'linkedin') {
        tasks.push(runOne(LINKEDIN_ACTOR, {
            keywords: title,
            location,
            limitPerSource: limit,
            scrapeCompany: false,
        }, 'linkedin', normalizeLinkedIn));
    }

    if (source === 'both' || source === 'indeed') {
        tasks.push(runOne(INDEED_ACTOR, {
            position: title,
            location,
            country,
            maxItemsPerSearch: limit,
            parseCompanyDetails: false,
            saveOnlyUniqueItems: true,
            followApplyRedirects: false,
        }, 'indeed', normalizeIndeed));
    }

    const seen = new Set();
    return (await Promise.all(tasks)).flat().filter((j) => {
        if (!j.url) return true;
        if (seen.has(j.url)) return false;
        seen.add(j.url);
        return true;
    });
}
