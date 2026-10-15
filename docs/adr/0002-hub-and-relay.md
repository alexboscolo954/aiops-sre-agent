---
status: proposed
---

# One Hub reasons for every Contract; Relays only run tools

One Hub runs the agent's reasoning for every Contract. A Contract is reached either Direct, where the Hub holds its credentials, or through a Relay inside the client network. The Relay holds the credentials, runs that Contract's MCP servers and dials out to the Hub. The Hub then drives an MCP session over that outbound connection, so the tools stay ordinary MCP servers and the client network accepts no inbound traffic.

The Hub, not the tool server, decides whether a tool reads or writes. Every vendor or Relay tool must be on the Contract's allowlist with its read or write status stated there. Tools not on the allowlist are hidden from the agent. A server's own read-only annotation can only make a tool stricter, never looser, so a write tool mislabelled as read-only still waits for approval.

## Considered Options

- **The whole agent inside each client network.** Tool output would never leave the client, but it means N deployments to upgrade, an LLM key reachable from each client network, and knowledge and evals split per site. Held back until a Contract forbids tool output leaving its network.
- **A central Hub with only Direct access.** Simpler, but it needs inbound access to every client network, which some clients refuse.
