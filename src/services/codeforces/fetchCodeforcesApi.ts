export async function fetchCodeforcesApi(url: string) {
  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP error! Status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  }
  catch (error) {
    console.error('Something went wrong:', (error as Error).message);
  }
}