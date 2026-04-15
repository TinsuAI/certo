import { promises as fs } from "node:fs";
import path from "node:path";
import { createExtractorFromFile } from "node-unrar-js";

const scanRoot = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(process.cwd(), "data", "extracted", "CO");

async function collectRars(dirPath, rarPaths) {
  const entries = await fs.readdir(dirPath, { withFileTypes: true });

  for (const entry of entries) {
    const nextPath = path.join(dirPath, entry.name);

    if (entry.isDirectory()) {
      await collectRars(nextPath, rarPaths);
      continue;
    }

    if (entry.isFile() && nextPath.toLowerCase().endsWith(".rar")) {
      rarPaths.push(nextPath);
    }
  }
}

async function ensureDirectory(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

async function extractArchive(archivePath) {
  const targetPath = path.join(
    path.dirname(archivePath),
    path.basename(archivePath, path.extname(archivePath)),
  );

  await ensureDirectory(targetPath);

  const extractor = await createExtractorFromFile({
    filepath: archivePath,
    targetPath,
  });
  const list = extractor.getFileList();
  const headers = [...list.fileHeaders];

  if (headers.length === 0) {
    return {
      archivePath,
      extractedCount: 0,
      targetPath,
    };
  }

  const extracted = extractor.extract();
  const files = [...extracted.files];
  const extractedCount = files.filter(
    (file) => !file.fileHeader.flags.directory,
  ).length;

  return {
    archivePath,
    extractedCount,
    targetPath,
  };
}

async function main() {
  const rarPaths = [];

  await collectRars(scanRoot, rarPaths);

  if (rarPaths.length === 0) {
    console.log(`No RAR archives found under ${scanRoot}`);
    return;
  }

  let extractedArchives = 0;
  let extractedFiles = 0;
  let failures = 0;

  for (const archivePath of rarPaths.sort((left, right) => left.localeCompare(right))) {
    try {
      const result = await extractArchive(archivePath);
      extractedArchives += 1;
      extractedFiles += result.extractedCount;

      console.log(
        `${path.relative(scanRoot, result.archivePath)} -> ${path.relative(scanRoot, result.targetPath)} (${result.extractedCount} files)`,
      );
    } catch (error) {
      failures += 1;
      const message = error instanceof Error ? error.message : String(error);
      console.error(`${path.relative(scanRoot, archivePath)} failed: ${message}`);
    }
  }

  console.log(
    `Processed ${rarPaths.length} archive(s): ${extractedArchives} succeeded, ${failures} failed, ${extractedFiles} file(s) extracted.`,
  );

  if (failures > 0) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
