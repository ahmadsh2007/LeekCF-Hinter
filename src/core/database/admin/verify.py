# ====================================================================================================
# WARNING:
# YOU SHOULD NOT RUN ANY OF THESE FILES AT ALL, UNLESS THERE IS A URGENT NEED TO RUN IT 
# AND THERE IS NO OTHER WAY TO FIX THE PROBLEM OR MAKE THE CHANGES BUT TO RUN ONE OF THESE FILES.
# ====================================================================================================

import random

def verifyAction() -> bool:
    print("This place is dangerous and may destroy the production")
    print("DO NOT USE THESE FILES BEFORE READING THE README.MD FILE\n")
    
    status = input("To proceed, write 'I_KNOW_WHAT_I_AM_DOING': ")
    if status != 'I_KNOW_WHAT_I_AM_DOING': 
        return False

    for i in range(1, 4):
        val = random.randint(1000, 9999)
        print(f"Process ({i}/3).")
        prompt = f"To proceed enter [{val}], or enter any random value to cancel: "
        
        try:
            inputVal = int(input(prompt))
            if inputVal != val: 
                return False
        except ValueError:
            return False

    finalCheck = input("Are you sure [y/n]: ")
    if finalCheck != 'y': 
        return False

    return True

if __name__ == "__main__":
    print("==========================================================================================")
    print(f"You are in verify.py file. It's just a test for the file, nothing dangerous here. Muhehehe")
    print("==========================================================================================\n")
    print('Success' if verifyAction() else 'Failure')