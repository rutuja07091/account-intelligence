// Row level security in Cube: the same rule semantic_layer.py
// applies, enforced on every query from Tableau, an app, or an AI agent.
// securityContext comes from the signed-in user's token.
module.exports = {
  queryRewrite: (query, { securityContext }) => {
    if (securityContext.territory) {
      query.filters.push({
        member: "accounts.territory",
        operator: "equals",
        values: [securityContext.territory],
      });
    }
    return query;
  },
};
