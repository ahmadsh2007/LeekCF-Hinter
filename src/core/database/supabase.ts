import { createClient } from "@supabase/supabase-js"
import dotenv from "dotenv"
import path from "path"

// Get keys from config/.env, or from the file named by ENV_FILE (e.g. to run against a staging project).
const envFile = process.env.ENV_FILE || "config/.env";
dotenv.config({ path: path.resolve(process.cwd(), envFile) })

const supabaseUrl = process.env.SUPABASE_DATABASE_URL;
const supabaseSecretKey = process.env.SUPABASE_DATABASE_SECRET_KEY;

if (!supabaseUrl || !supabaseSecretKey) {
  throw new Error(`Missing Supabase environment variables in ${envFile}`);
}

console.log(`Supabase target: ${new URL(supabaseUrl).hostname}`);

export const supabaseAdmin = createClient(supabaseUrl, supabaseSecretKey);