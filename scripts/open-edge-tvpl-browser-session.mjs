import { spawn } from "node:child_process";

const DEFAULT_PORT = process.env.TVPL_REMOTE_DEBUGGING_PORT || "9222";
const START_URL = process.env.TVPL_START_URL || "https://thuvienphapluat.vn/page/tim-van-ban.aspx?keyword=05%2F2018%2FTT-BCT&match=True&area=0";
const WINDOWS_EDGE_PATH = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const POWERSHELL_PATH = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe";

function runPowerShell(command) {
  return new Promise((resolve, reject) => {
    const child = spawn(POWERSHELL_PATH, ["-NoProfile", "-Command", command], {
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });

    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr || stdout || `PowerShell failed with code ${code}`));
        return;
      }
      resolve(stdout.trim());
    });
  });
}

async function main() {
  const launchCommand = [
    `$edge='${WINDOWS_EDGE_PATH}'`,
    `$url='${START_URL}'`,
    `$userData='C:\\Temp\\barry-co-tvpl-edge-${DEFAULT_PORT}'`,
    `$args=@('--remote-debugging-port=${DEFAULT_PORT}','--remote-debugging-address=0.0.0.0','--user-data-dir=' + $userData,'--new-window',$url)`,
    "Start-Process -FilePath $edge -ArgumentList $args",
  ].join("; ");

  await runPowerShell(launchCommand);
  console.log(JSON.stringify({
    remoteDebuggingUrl: `http://127.0.0.1:${DEFAULT_PORT}`,
    startUrl: START_URL,
    browser: "edge",
  }, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
