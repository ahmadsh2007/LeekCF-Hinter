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
    
    table:        str = input("Enter table name (case sensitive): ")
    filterColumn: str = input("Enter filter/column name (case sensitive): ")
    fromVal:      str = input("Enter the old value (case sensitive): ")
    toVal:        str = input("Enter the new value (case sensitive): ")
    hasTimestamp: str = input("Does this table have an 'updated_at' column? (y/n): ").strip().lower()

    updatePayload = {filterColumn: toVal}
    if hasTimestamp == 'y':
        updatePayload["updated_at"] = "now()"

    print(f"\nExecuting update on table '{table}'...")
    try:
        response = (
            supabase.table(table)
            .update(updatePayload)
            .eq(filterColumn, fromVal)
            .execute()
        )
        print(f"Successfully updated {len(response.data)} records in table '{table}'!")
    except Exception as e:
        print(f"Database Error: {e}. GG WE DIED")
if __name__ == "__main__":
    changeDatabaseValueViaBulkChange()