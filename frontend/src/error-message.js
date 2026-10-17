export function errorMessage(error) {
  const message = typeof error === 'string' ? error : error?.message;
  if (!message || typeof message !== 'string') return 'Something went wrong. Please try again.';
  if (/^(failed to fetch|fetch failed|load failed|network\s?error|network request failed|the network connection was lost)/i.test(message)) {
    return 'The connection was interrupted. Check your internet connection and try again.';
  }
  if (message === 'Recommendation stream ended before completion') {
    return 'The search connection closed before it finished. Your results are kept; choose Search more to continue.';
  }
  return message;
}
