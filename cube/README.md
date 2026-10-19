# The semantic model in Cube

`model/cases.yml` defines the `cases`, `accounts`, and `physicians` cubes, and `cube.js` adds row level security: a user whose token carries a territory only ever sees that territory, whatever they ask for.

This was run locally with Cube 1.8.8 on the demo DuckDB file. It returns exactly the same numbers as the Python semantic layer (for example, 16,800 Gulf Coast cases from both), and a TAM token asking for another territory gets 0.

## Run it (optional, about 10 minutes)

Needs Node.js 22 or newer (nodejs.org). From the project root, after `python generate_data.py`:

```bash
python cube/prepare_cube_db.py     # copies the data and adds a `commercial` schema, like Redshift
cd cube
cp .env.example .env
npm install                        # first install takes a few minutes
npm start                          # Cube at http://localhost:4000
```

In a second terminal, `cd cube` and run `npm run demo`. It asks the same question as the Regional VP and as Jordan Pike (TAM, Ohio Valley) and prints both results: six territories for the VP, only Ohio Valley for Jordan.

`CUBEJS_DEV_MODE=true` also opens Cube's Playground at http://localhost:4000, where you can click through measures and see the generated SQL.

## What to say about it

- One definition of each metric, in Git, reviewed by pull request, consumed by Tableau, apps, and AI agents alike.
- Security is enforced once, in `queryRewrite`, not separately in every dashboard.
- The demo app uses a small Python version of the same idea (`semantic_layer.py`) so it runs without Node; this folder shows the production-shaped version.
