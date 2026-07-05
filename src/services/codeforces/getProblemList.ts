import { fetchCodeforcesApi } from './fetchCodeforcesApi.ts'

export async function getProblemList() {
  try{
    const url = 'https://codeforces.com/api/problemset.problems'
    const data = await fetchCodeforcesApi(url);

    if (!data) {
      throw new Error('No data received from API fetcher')
    }

    if (data.status === "OK") {
      console.log("Success! Problems fetched successfully");
      console.log(`Total problems found: ${data.result.problems.length}`);

      // console.log(data);

      return data.result.problems
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