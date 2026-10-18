# ====================================================================================================
# WARNING:
# YOU SHOULD NOT RUN ANY OF THESE FILES AT ALL, UNLESS THERE IS A URGENT NEED TO RUN IT 
# AND THERE IS NO OTHER WAY TO FIX THE PROBLEM OR MAKE THE CHANGES BUT TO RUN ONE OF THESE FILES.
# ====================================================================================================

from src.core.database.dbClient import supabase
from src.core.database.admin.verify import verifyAction

def changeDatabaseValueViaBulkChange():
    if not verifyAction():
        print("Verification failed. Process cancelled. No changes made. THANK GOD NOTHING HAPPENED")
        return
    
    tagToMatch: str = input("Enter the tag value to match and delete [default: *special]: ").strip() or "*special"

    try:
        print(f"\nStep 1: Finding problems where tags contains '{tagToMatch}'...")
        problems_res = (
            supabase.table("problems")
            .select("id, canonical_problem_id")
            .contains("tags", [tagToMatch])
            .execute()
        )

        # Duplicates go first: a canonical problem cannot be deleted while a duplicate still points at it.
        rows = sorted(problems_res.data, key=lambda row: row["canonical_problem_id"] is None)
        problemIDs = [row["id"] for row in rows]

        if not problemIDs:
            print(f"No problems found with tag '{tagToMatch}'. Database untouched.")
            return

        totalProblems = len(problemIDs)
        print(f"Found {totalProblems} problem(s) to remove across all tables.")

        chunkSize = 100
        idChunk = [problemIDs[i:i + chunkSize] for i in range(0, totalProblems, chunkSize)]

        print("\nStep 2: Deleting records from 'problems' (specs, sample tests, tutorials and hints go with them via ON DELETE CASCADE)...")
        totalDeletedProblems = 0
        for chunk in idChunk:
            res = supabase.table("problems").delete().in_("id", chunk).execute()
            totalDeletedProblems += len(res.data)

        print(f"\nSuccessfully purged {totalDeletedProblems} problem(s) and all linked data!")
    except Exception as e:
        print(f"Database Error: {e}. GG WE DIED")
        
if __name__ == "__main__":
    changeDatabaseValueViaBulkChange()