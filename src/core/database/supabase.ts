import { createClient } from "@supabase/supabase-js"
import dotenv from "dotenv"
import path from "path"

// Get keys from config/.env. If you put .env in the root, use ".env"
dotenv.config({ path: path.resolve(process.cwd(), "config/.env") })

const supabaseUrl = process.env.SUPABASE_DATABASE_URL;
const supabaseSecretKey = process.env.SUPABASE_DATABASE_SECRET_KEY;

if (!supabaseUrl || !supabaseSecretKey) {
  throw new Error("Missing Supabase environment variables in config/.env");
}

export const supabaseAdmin = createClient(supabaseUrl, supabaseSecretKey);