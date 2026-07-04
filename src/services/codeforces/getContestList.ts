import { fetchCodeforcesApi } from './fetchCodeforcesApi.ts'

export async function getContestList() {
  try{
    const url = 'https://codeforces.com/api/contest.list?gym=false'
    const data = await fetchCodeforcesApi(url);

    if (!data) {
      throw new Error('No data received from API fetcher')
    }

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