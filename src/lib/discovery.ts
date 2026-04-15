import { promises as fs } from "node:fs";
import path from "node:path";

const dataRoot = path.join(process.cwd(), "data", "extracted", "CO");
const statusBuckets = new Set(["Chưa hoàn thiện", "Đã hoàn thiện"]);
const workflowFolder = "Quy trình xin CO + file chạy dữ liệu CO";
const archiveExtensions = new Set(["zip", "rar"]);

type MutableGroup = {
  archiveCount: number;
  caseNames: Set<string>;
  documentCount: number;
  name: string;
  samples: DiscoveryFile[];
};

export type DiscoveryFile = {
  extension: string;
  relativePath: string;
  sizeInBytes: number;
};

export type DiscoveryGroup = {
  archiveCount: number;
  caseCount: number;
  documentCount: number;
  name: string;
  samples: DiscoveryFile[];
};

export type DiscoverySnapshot = {
  available: boolean;
  extensionCounts: Array<{ count: number; extension: string }>;
  groups: DiscoveryGroup[];
  remainingArchives: DiscoveryFile[];
  rootLabel: string;
  scannedAt: string;
  totalDocuments: number;
  workflowFiles: DiscoveryFile[];
};

async function pathExists(targetPath: string) {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function collectFiles(dirPath: string, files: string[]) {
  const entries = await fs.readdir(dirPath, { withFileTypes: true });

  for (const entry of entries) {
    const nextPath = path.join(dirPath, entry.name);

    if (entry.isDirectory()) {
      await collectFiles(nextPath, files);
      continue;
    }

    if (entry.isFile()) {
      files.push(nextPath);
    }
  }
}

function getExtension(filePath: string) {
  return path.extname(filePath).replace(".", "").toLowerCase() || "none";
}

function toRelativePath(filePath: string) {
  return path.relative(dataRoot, filePath).split(path.sep).join("/");
}

function sortFiles(files: DiscoveryFile[]) {
  return [...files].sort((left, right) =>
    left.relativePath.localeCompare(right.relativePath, "en"),
  );
}

function finalizeGroups(groups: Map<string, MutableGroup>) {
  return [...groups.values()]
    .map((group) => ({
      archiveCount: group.archiveCount,
      caseCount: group.caseNames.size,
      documentCount: group.documentCount,
      name: group.name,
      samples: sortFiles(group.samples),
    }))
    .sort((left, right) => right.documentCount - left.documentCount);
}

export async function getDiscoverySnapshot(): Promise<DiscoverySnapshot> {
  if (!(await pathExists(dataRoot))) {
    return {
      available: false,
      extensionCounts: [],
      groups: [],
      remainingArchives: [],
      rootLabel: "data/extracted/CO",
      scannedAt: new Date().toISOString(),
      totalDocuments: 0,
      workflowFiles: [],
    };
  }

  const files: string[] = [];
  await collectFiles(dataRoot, files);

  const extensionCounts = new Map<string, number>();
  const groups = new Map<string, MutableGroup>();
  const remainingArchives: DiscoveryFile[] = [];
  const workflowFiles: DiscoveryFile[] = [];
  let totalDocuments = 0;

  for (const filePath of files) {
    const relativePath = toRelativePath(filePath);
    const segments = relativePath.split("/");
    const sectionName = segments[0] ?? "root";
    const extension = getExtension(filePath);
    const stats = await fs.stat(filePath);
    const isArchive = archiveExtensions.has(extension);
    const fileRecord: DiscoveryFile = {
      extension,
      relativePath,
      sizeInBytes: stats.size,
    };

    const group =
      groups.get(sectionName) ??
      {
        archiveCount: 0,
        caseNames: new Set<string>(),
        documentCount: 0,
        name: sectionName,
        samples: [],
      };

    if (statusBuckets.has(sectionName) && segments[1]) {
      group.caseNames.add(segments[1]);
    }

    if (isArchive) {
      group.archiveCount += 1;
      remainingArchives.push(fileRecord);
    } else {
      group.documentCount += 1;
      totalDocuments += 1;
      extensionCounts.set(extension, (extensionCounts.get(extension) ?? 0) + 1);

      if (group.samples.length < 4) {
        group.samples.push(fileRecord);
      }

      if (sectionName === workflowFolder) {
        workflowFiles.push(fileRecord);
      }
    }

    groups.set(sectionName, group);
  }

  return {
    available: true,
    extensionCounts: [...extensionCounts.entries()]
      .map(([extension, count]) => ({ count, extension }))
      .sort((left, right) => right.count - left.count),
    groups: finalizeGroups(groups),
    remainingArchives: sortFiles(remainingArchives),
    rootLabel: "data/extracted/CO",
    scannedAt: new Date().toISOString(),
    totalDocuments,
    workflowFiles: sortFiles(workflowFiles),
  };
}
