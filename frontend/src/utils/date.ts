/**
 * Date formatting utility for the SETU AI Commerce system.
 * Parsers assume input is in UTC and output format in Asia/Kolkata (IST).
 */
export const formatDate = (
  dateStr: string | null | undefined,
  includeSeconds: boolean = false
): string => {
  if (!dateStr) return 'N/A';
  
  // Ensure the date string has a timezone offset designator if it lacks one
  // so the browser interprets it strictly as UTC rather than local time.
  let formattedStr = dateStr;
  if (
    formattedStr && 
    !formattedStr.includes('Z') && 
    !formattedStr.includes('+') && 
    !formattedStr.match(/-\d{2}:\d{2}$/)
  ) {
    // If it's a raw ISO string without timezone (e.g. 2026-08-30T13:48:52)
    formattedStr = formattedStr + 'Z';
  }
  
  try {
    const d = new Date(formattedStr);
    if (isNaN(d.getTime())) {
      return 'Invalid Date';
    }
    
    return new Intl.DateTimeFormat("en-IN", {
      timeZone: "Asia/Kolkata",
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: includeSeconds ? "2-digit" : undefined,
      hour12: true
    }).format(d);
  } catch (err) {
    console.error('Date formatting error:', err);
    return 'Invalid Date';
  }
};
