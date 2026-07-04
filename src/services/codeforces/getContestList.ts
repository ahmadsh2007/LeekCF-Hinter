export async function fetchContestList() {
  try{
    const response = await fetch(`https://codeforces.com/api/contest.list?gym=false`);
    if (!response.ok) {
      throw new Error(`HTTP error! Status: ${response.status}`);
    }

    const data = await response.json();
    if (data.status === "OK") {
      console.log("Success! Contests fetched successfully");
      console.log(`Total contests found: ${data.result.length}`);

      // console.log(data);

      return data.result
    }
    else {
      throw new Error(`Codeforces API Error: ${data.comment}`);
    }
  }
  catch (error) {
    console.error('Something went wrong:', (error as Error).message);
    return [];
  }
}

fetchContestList()