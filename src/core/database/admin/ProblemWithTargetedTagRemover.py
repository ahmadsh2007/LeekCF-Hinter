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
            .select("id")
            .contains("tags", [tagToMatch])
            .execute()
        )
        
        problemIDs = [row["id"] for row in problems_res.data]
        
        if not problemIDs:
            print(f"No problems found with tag '{tagToMatch}'. Database untouched.")
            return

        totalProblems = len(problemIDs)
        print(f"Found {totalProblems} problem(s) to remove across all tables.")

        # Tables with foreign keys pointing to problems
        dependent_tables = [
            "problem_specifications",
            "interactive_problem_specifications",
            "sample_tests",
            "sample_tests_ARCHIEVED",
            "hints",
            "tutorials",
        ]

        chunkSize = 100
        idChunk = [problemIDs[i:i + chunkSize] for i in range(0, totalProblems, chunkSize)]

        print("\nStep 2: Deleting dependent data from child tables...")
        for table in dependent_tables:
            deletedCount = 0
            for chunk in idChunk:
                try:
                    res = supabase.table(table).delete().in_("problem_id", chunk).execute()
                    deletedCount += len(res.data)
                except Exception as e:
                    pass
            print(f"  - [{table}]: Removed {deletedCount} record(s)")

        print("\nStep 3: Deleting records from 'problems'...")
        totalDeletedProblems = 0
        for chunk in idChunk:
            res = supabase.table("problems").delete().in_("id", chunk).execute()
            totalDeletedProblems += len(res.data)

        print(f"\nSuccessfully purged {totalDeletedProblems} problem(s) and all linked data!")
    except Exception as e:
        print(f"Database Error: {e}. GG WE DIED")
        
if __name__ == "__main__":
    changeDatabaseValueViaBulkChange()