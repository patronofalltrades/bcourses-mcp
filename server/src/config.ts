export interface Config {
  canvasBaseUrl: string;
  canvasAccessToken: string;
  port: number;
}

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

export function loadConfig(): Config {
  const rawBaseUrl = process.env.BCOURSES_BASE_URL?.trim() || "https://bcourses.berkeley.edu";
  const url = new URL(rawBaseUrl);
  if (url.protocol !== "https:" && url.hostname !== "localhost" && url.hostname !== "127.0.0.1") {
    throw new Error("BCOURSES_BASE_URL must use HTTPS unless it points to localhost");
  }

  const port = Number(process.env.PORT || "3000");
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("PORT must be an integer between 1 and 65535");
  }

  return {
    canvasBaseUrl: url.origin,
    canvasAccessToken: required("BCOURSES_ACCESS_TOKEN"),
    port,
  };
}
