import 'dotenv/config';
import { writeFile } from 'node:fs/promises';
import { scrapeJobs } from './lib/apify.js';

// --title "Software Engineer" --location "Bengaluru" --country IN --limit 25 --source both
function parseArgs(argv) {
    const args = {};
    for (let i = 0; i < argv.length; i += 2) {
        const key = argv[i]?.replace(/^--/, '');
        if (key) args[key] = argv[i + 1];
    }
    return {
        title: args.title || 'Software Engineer',
        location: args.location || 'Bengaluru',
        country: (args.country || 'IN').toUpperCase(),
        limit: Number(args.limit || 25),
        source: (args.source || 'both').toLowerCase(),
    };
}

async function main() {
    const opts = parseArgs(process.argv.slice(2));

    const token = process.env.APIFY_API_KEY;
    if (!token) throw new Error('APIFY_API_KEY .env me nahi mila');

    console.log('Search config:', opts);

    const jobs = await scrapeJobs({ ...opts, token }, (stage, msg) => console.log(`[${stage}] ${msg}`));

    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const jsonPath = `jobs-${stamp}.json`;
    await writeFile(jsonPath, JSON.stringify(jobs, null, 2), 'utf8');

    const csvCols = ['source', 'title', 'company', 'location', 'postedAt', 'contractType', 'salary', 'url'];
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""').replace(/\s+/g, ' ').trim()}"`;
    const csv = [csvCols.join(','), ...jobs.map((j) => csvCols.map((c) => esc(j[c])).join(','))].join('\n');
    const csvPath = `jobs-${stamp}.csv`;
    await writeFile(csvPath, csv, 'utf8');

    console.log(`\nTotal ${jobs.length} jobs -> ${jsonPath} / ${csvPath}`);
    console.table(jobs.slice(0, 15).map((j) => ({
        source: j.source,
        title: (j.title || '').slice(0, 45),
        company: (j.company || '').slice(0, 25),
        location: (j.location || '').slice(0, 25),
    })));
}

main().catch((err) => {
    console.error(err);
    process.exit(1);
});
