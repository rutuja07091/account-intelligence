// Starts a local Cube server using the model in ./model and the rules in ./cube.js.
require("dotenv/config");
const CubejsServer = require("@cubejs-backend/server");
new CubejsServer(require("./cube.js")).listen().then(({ port }) => {
  console.log(`Cube is running on http://localhost:${port}`);
});
