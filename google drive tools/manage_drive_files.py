#!/usr/bin/env python3
import os
import io
import time
import threading
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/drive']

# Global variable to track search progress
search_progress_count = 0
search_in_progress = False

def get_detailed_error_message(error: HttpError) -> str:
    """Extracts a more detailed error message from an HttpError."""
    try:
        error_content = json.loads(error.content)
        if 'error' in error_content and 'message' in error_content['error']:
            return error_content['error']['message']
        elif 'error_description' in error_content:
            return error_content['error_description']
    except (json.JSONDecodeError, KeyError):
        pass
    return str(error)

def handle_common_api_errors(error: HttpError, operation: str):
    """Provides user-friendly advice for common Google Drive API errors."""
    detailed_msg = get_detailed_error_message(error)
    print(f"API Error during {operation}: {detailed_msg}")

    if error.resp.status == 403: # Forbidden
        print("  Possible Cause: You might not have the necessary permissions to perform this action (e.g., delete files you don't own, or access is restricted).")
        print("  Suggestion: Ensure your Google account has full access to the files/folders in question and the Drive API is enabled for your project.")
    elif error.resp.status == 404: # Not Found
        print("  Possible Cause: The file or resource could not be found. It might have already been deleted, moved, or the ID is incorrect.")
        print("  Suggestion: Verify the file's existence in your Google Drive.")
    elif error.resp.status == 400: # Bad Request
        print("  Possible Cause: The request was malformed or missing required parameters.")
        print("  Suggestion: This usually indicates an issue with the script's query or parameters. Review the script's logic.")
    elif error.resp.status == 429: # Too Many Requests
        print("  Possible Cause: You have sent too many requests in a given amount of time (rate limiting).")
        print("  Suggestion: Google imposes usage limits. If this occurs frequently, you may need to implement a delay between operations or request a higher quota.")
    elif error.resp.status >= 500: # Server Errors
        print("  Possible Cause: A temporary issue with Google's servers.")
        print("  Suggestion: Try running the script again after a short while.")
    else:
        print("  Suggestion: Check Google Drive API documentation or Google Cloud Console for more details on this specific error code.")

def authenticate_google_drive():
    """Authenticates with Google Drive API and returns the service object."""
    print("Initiating Google Drive authentication process...")
    creds = None
    if os.path.exists('token.json'):
        print("Found existing token.json. Attempting to use saved credentials.")
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Credentials expired. Attempting to refresh token...")
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"ERROR: Failed to refresh token: {e}")
                print("Please delete 'token.json' and 'credentials.json' (if you downloaded a new one) and try running the script again.")
                return None
        else:
            print("No valid credentials found or token expired/invalid. Starting new authentication flow.")
            print("You will be prompted to open a browser window to complete authentication.")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            except FileNotFoundError:
                print("ERROR: 'credentials.json' not found. Please ensure you have downloaded it from Google Cloud Console and placed it in the same directory as the script.")
                return None
            except Exception as e:
                print(f"ERROR: An unexpected error occurred during the authentication flow: {e}")
                return None
        
        print("Authentication successful. Saving credentials to token.json for future use.")
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    else:
        print("Credentials are valid.")

    try:
        print("Building Google Drive service object...")
        service = build('drive', 'v3', credentials=creds)
        print("Google Drive service object created successfully.")
        return service
    except HttpError as error:
        print(f"ERROR: An HttpError occurred during service building (status: {error.resp.status}).")
        handle_common_api_errors(error, "service building")
        return None
    except Exception as e:
        print(f"ERROR: An unexpected error occurred while building Google Drive service: {e}")
        return None

def display_search_progress():
    """Function to display search progress every few seconds."""
    global search_progress_count
    global search_in_progress
    
    start_time = time.time()
    while search_in_progress:
        time.sleep(10)
        if search_in_progress:
            elapsed_time = int(time.time() - start_time)
            print(f"SEARCH PROGRESS: {search_progress_count} files found so far... ({elapsed_time} seconds elapsed)")

def find_files_for_trash(service, filename_part_to_search):
    """
    Finds files in 'My Drive' where the filename contains the specified string,
    excluding shared drives, and returns a list of file IDs and names.
    """
    global search_progress_count
    global search_in_progress

    if not service:
        print("ERROR: Google Drive service not available for search.")
        return []

    print(f"\nStarting search for files with names containing '{filename_part_to_search}' in your 'My Drive'...")
    print("This may take some time depending on the number of files and your connection speed.")
    print("Fetching results in pages of up to 1000 files...")

    files_to_trash = []
    page_token = None
    search_progress_count = 0
    search_in_progress = True

    # Start the progress display thread
    progress_thread = threading.Thread(target=display_search_progress)
    progress_thread.daemon = True
    progress_thread.start()

    try:
        while True:
            query = f"name contains '{filename_part_to_search}' and trashed = false and mimeType != 'application/vnd.google-apps.folder' and 'me' in owners"
            
            print(f"  Requesting next page of results (currently found {len(files_to_trash)} files)...")
            results = service.files().list(
                q=query,
                spaces='drive',
                fields='nextPageToken, files(id, name, parents, shared, ownedByMe)',
                includeItemsFromAllDrives=False,
                corpora='user',
                pageSize=1000,
                pageToken=page_token
            ).execute()

            items = results.get('files', [])
            print(f"  Received {len(items)} items in the current page.")

            for item in items:
                file_id = item['id']
                file_name = item['name']
                owned_by_me = item.get('ownedByMe', False)

                is_in_shared_drive = False
                if 'parents' in item:
                    for parent_id in item['parents']:
                        try:
                            parent_file = service.files().get(fileId=parent_id, fields='isSharedDrive').execute()
                            if parent_file.get('isSharedDrive', False):
                                is_in_shared_drive = True
                                break
                        except HttpError:
                            pass

                if owned_by_me and not is_in_shared_drive:
                    files_to_trash.append({'id': file_id, 'name': file_name})
                    search_progress_count += 1
            
            page_token = results.get('nextPageToken', None)
            if not page_token:
                print("  No more pages of results. Finishing search.")
                break

    except HttpError as error:
        print(f"\nERROR: An HttpError occurred during file listing (status: {error.resp.status}).")
        handle_common_api_errors(error, "file listing")
    except Exception as e:
        print(f"\nERROR: An unexpected error occurred during file search: {e}")
    finally:
        search_in_progress = False
        progress_thread.join(timeout=15)

    print(f"\nSearch complete. Found a total of {len(files_to_trash)} files that meet the criteria.")
    return files_to_trash

# --- Callback for batch requests ---
def batch_callback(request_id, response, exception):
    """Callback function for individual responses in a batch."""
    global files_processed_in_batch
    global files_failed_in_batch
    
    files_processed_in_batch += 1
    file_name = response.get('name', 'Unknown File') if response else "Unknown File" # Attempt to get name from response

    if exception:
        files_failed_in_batch += 1
        print(f"  Batch operation for request ID {request_id} (File: {file_name}) FAILED: {exception}")
        # Further detailed error handling for individual batch items can be added here
        # For HttpError in batch, exception.resp.status and exception.content can be useful
    else:
        # print(f"  Batch operation for request ID {request_id} (File: {file_name}) SUCCESS.")
        pass # Keep output cleaner for successful batch items

# Global variables for batch progress tracking
files_processed_in_batch = 0
files_failed_in_batch = 0

def move_files_to_trash(service, files_to_move, batch_size=100):
    """
    Moves a list of files to the Google Drive trash using batch requests.
    """
    global files_processed_in_batch
    global files_failed_in_batch

    if not service:
        print("ERROR: Google Drive service not available for moving files.")
        return

    if not files_to_move:
        print("No files to move to trash. Skipping operation.")
        return

    total_files = len(files_to_move)
    print(f"\nProceeding to move {total_files} file(s) to trash using batch requests (batch size: {batch_size})...")

    files_processed_in_batch = 0
    files_failed_in_batch = 0
    
    for i in range(0, total_files, batch_size):
        batch = service.new_batch_http_request(callback=batch_callback)
        batch_slice = files_to_move[i:i + batch_size]
        
        print(f"  Processing batch {int(i/batch_size) + 1} of {int((total_files + batch_size - 1) / batch_size)} ({len(batch_slice)} files)...")

        for file_data in batch_slice:
            file_id = file_data['id']
            file_name = file_data['name']
            # We don't add specific print statements here, as the callback handles individual item feedback.
            batch.add(service.files().update(fileId=file_id, body={'trashed': True}), request_id=file_name) # Using filename as request_id for clarity in callback

        try:
            batch.execute()
            print(f"  Batch {int(i/batch_size) + 1} execution complete. (Processed: {files_processed_in_batch}, Failed: {files_failed_in_batch})")
        except HttpError as error:
            print(f"  ERROR: An HttpError occurred during batch execution (status: {error.resp.status}).")
            handle_common_api_errors(error, "batch file trash")
            # Note: Batch errors might also contain individual sub-request errors in their content
            # For simplicity, we're relying on the callback for individual item errors.
        except Exception as e:
            print(f"  ERROR: An unexpected error occurred during batch execution: {e}")

    print(f"\nBatch trashing operation complete.")
    print(f"Total files attempted: {total_files}")
    print(f"Total files processed (including successful/failed in batches): {files_processed_in_batch}")
    print(f"Total files failed: {files_failed_in_batch}")


if __name__ == '__main__':
    print("Starting Google Drive File Management Script...")
    service = authenticate_google_drive()
    
    if service:
        filename_part = input("\nEnter a part of the filename you would like to search for in your My Drive (e.g., 'report', 'backup'): ")
        
        matching_files = find_files_for_trash(service, filename_part)

        if not matching_files:
            print(f"\nNo files found with names containing '{filename_part}' in your 'My Drive' that you own and are not in a shared drive.")
        else:
            num_matches = len(matching_files)
            print(f"\nSummary: Found {num_matches} file(s) matching '{filename_part}' in your 'My Drive'.")
            
            print("\nSample files that will be moved to trash (showing up to 5):")
            for i, file_data in enumerate(matching_files[:5]):
                print(f"  - {file_data['name']}")
            if num_matches > 5:
                print(f"  ...and {num_matches - 5} more files not listed here.")

            confirmation = input(f"\nCONFIRMATION: Do you want to move these {num_matches} file(s) to your Google Drive trash? (yes/no): ").lower()
            
            if confirmation == 'yes':
                move_files_to_trash(service, matching_files)
                print("\nOperation complete. Please check your Google Drive trash for the moved files. Remember to empty your trash if you want to permanently delete them.")
            else:
                print("Operation cancelled by user. No files were moved to trash.")
    else:
        print("\nScript aborted due to authentication failure or service unavailability.")
    print("Script finished.")
