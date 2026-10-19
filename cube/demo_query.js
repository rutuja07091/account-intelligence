// Asks Cube the same question as two different users, to show row level security.
// Run while the server is up:  npm run demo
require("dotenv/config");
const jwt = require("jsonwebtoken");

const secret = process.env.CUBEJS_API_SECRET;
const users = {
  "Regional VP (all territories)": {},
  "Jordan Pike, TAM Ohio Valley": { territory: "Ohio Valley" },
};
const query = { measures: ["cases.case_count", "cases.plaque_share"], dimensions: ["accounts.territory"] };

async function load(token) {
  const url = "http://localhost:4000/cubejs-api/v1/load?query=" + encodeURIComponent(JSON.stringify(query));
  for (let i = 0; i < 10; i++) {
    const body = await (await fetch(url, { headers: { Authorization: token } })).json();
    if (!body.error || body.error !== "Continue wait") return body;
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error("Cube did not answer in time");
}

(async () => {
  for (const [who, context] of Object.entries(users)) {
    const body = await load(jwt.sign(context, secret));
    console.log(`\n${who}`);
    console.table(body.data.map((r) => ({
      territory: r["accounts.territory"],
      cases: Number(r["cases.case_count"]),
      plaque_share: Number(r["cases.plaque_share"]).toFixed(3),
    })));
  }
})();
