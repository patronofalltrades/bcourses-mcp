#!/usr/bin/env node
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CanvasClient } from "./canvas-client.js";
import { loadConfig } from "./config.js";
import { createServer } from "./server.js";

async function main() {
  const config = loadConfig();
  const server = createServer(new CanvasClient(config.canvasBaseUrl, config.canvasAccessToken));
  await server.connect(new StdioServerTransport());
  console.error("bCourses student MCP running over stdio");
}

main().catch(error => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
