import { readFile } from 'fs/promises'
import { join } from 'path';

const __dir = 'config/'
const __fileName = 'IGNORE_THESE_CONTESTS'

export async function readContestsID(dir: string = __dir, fileName: string = __fileName): Promise<number[]> {
  const filePath = join(dir, fileName);
  const data = await readFile(filePath, 'utf-8'); 

  const lines = data.split(/\r?\n/);
  const integers: number[] = [];

  for (const line of lines) {
    const trimmedLine = line.trim();

    if (trimmedLine.startsWith('#') || trimmedLine === '') {
      continue;
    }

    const parsedNumber = parseInt(trimmedLine, 10);

    if (!isNaN(parsedNumber)) {
      integers.push(parsedNumber);
    } else {
      console.warn(`Skipped invalid line: "${line}"`);
    }
  }

  return integers;
}