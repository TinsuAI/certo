import { spawn, spawnSync } from "node:child_process";
import path from "node:path";

const POWERSHELL_PATH = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe";
const WINDOWS_NODE_PATH = "C:\\Program Files\\nodejs\\node.exe";

function toWindowsPath(targetPath) {
  const result = spawnSync("wslpath", ["-w", targetPath], {
    encoding: "utf8",
  });

  if (result.status !== 0) {
    throw new Error(result.stderr.trim() || `wslpath failed for ${targetPath}`);
  }

  return result.stdout.trim();
}

async function main() {
  const targetUrl = process.argv[2] || process.env.TVPL_URL;
  if (!targetUrl) {
    throw new Error("Provide a TVPL URL as argv[2] or TVPL_URL.");
  }

  const repoWindowsPath = toWindowsPath(process.cwd());
  const scriptWindowsPath = toWindowsPath(
    path.join(process.cwd(), "scripts", "tvpl-human-assisted-fetch.mjs"),
  );

  const browserPreference = (process.env.TVPL_WINDOWS_BROWSER || "edge")
    .replace(/'/g, "''");
  const escapedUrl = targetUrl.replace(/'/g, "''");
  const escapedRepoPath = repoWindowsPath.replace(/'/g, "''");
  const escapedScriptPath = scriptWindowsPath.replace(/'/g, "''");

  const command = [
    `$env:TVPL_BROWSER_MODE='headful'`,
    `$env:TVPL_WINDOWS_BROWSER='${browserPreference}'`,
    `Set-Location '${escapedRepoPath}'`,
    `& '${WINDOWS_NODE_PATH}' '${escapedScriptPath}' '${escapedUrl}'`,
  ].join("; ");

  await new Promise((resolve, reject) => {
    const child = spawn(
      POWERSHELL_PATH,
      ["-NoProfile", "-Command", command],
      { stdio: "inherit" },
    );

    child.on("close", (code) => {
      if (code === 0) {
        resolve();
        return;
      }

      reject(new Error(`Windows TVPL fetch exited with code ${code}`));
    });
  });
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
