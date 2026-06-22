#!/usr/bin/env python3

import os
import csv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Using a strictly read-only scope for safety
SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly']

def authenticate_google_drive():
    """Authenticates with Google Drive API and returns the service object."""
    print("Initiating Google Drive authentication process...")
    creds = None
    
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"ERROR: Failed to refresh token. Please delete 'token.json' and try again.")
                return None
        else:
            print("Starting new authentication flow (Read-Only Mode).")
            try:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            except FileNotFoundError:
                print("ERROR: 'credentials.json' not found in this directory.")
                return None
        
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('drive', 'v3', credentials=creds)
        print("Google Drive service object created successfully.")
        return service
    except HttpError as error:
        print(f"ERROR: Could not build service: {error}")
        return None

def find_shared_files(service):
    """
    Fetches all files owned by the user and filters for the 'shared' property.
    Includes files from 'My Drive' and synced 'Computers'.
    """
    if not service:
        return []

    print("\nScanning your Drive and Computers for files you own that are shared with others...")
    print("Since we have to check every file you own, this may take a minute or two...")

    shared_files = []
    page_token = None
    files_scanned = 0

    try:
        while True:
            # Query for files the user owns that aren't in the trash
            query = "'me' in owners and trashed = false"
            
            results = service.files().list(
                q=query,
                spaces='drive', # 'drive' space inherently includes My Drive and Computers
                fields='nextPageToken, files(id, name, mimeType, shared, webViewLink)',
                includeItemsFromAllDrives=False,
                corpora='user',
                pageSize=1000, # Maximize batch size for speed
                pageToken=page_token
            ).execute()

            items = results.get('files', [])
            files_scanned += len(items)
            
            # Client-side check: Keep it only if the 'shared' flag is True
            for item in items:
                if item.get('shared') is True:
                    shared_files.append(item)
            
            print(f"  Scanned {files_scanned} files... (Found {len(shared_files)} shared so far)")

            page_token = results.get('nextPageToken', None)
            if not page_token:
                print("  No more pages to scan. Finishing search.")
                break

    except HttpError as error:
        print(f"\nERROR: An API error occurred: {error}")
    except Exception as e:
        print(f"\nERROR: An unexpected error occurred: {e}")

    return shared_files

def export_to_csv(shared_files, filename="shared_files_audit.csv"):
    """
    Saves the list of shared files to a CSV for easy viewing.
    """
    if not shared_files:
        print("\nGreat news! We found 0 files that you have shared with others.")
        return

    print(f"\nPreparing to export {len(shared_files)} shared files to {filename}...")
    headers = ['File Name', 'File ID', 'MIME Type', 'Direct Link']
    
    try:
        with open(filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(headers)
            
            for f in shared_files:
                writer.writerow([
                    f.get('name', 'Unknown'),
                    f.get('id', 'Unknown'),
                    f.get('mimeType', 'Unknown'),
                    f.get('webViewLink', 'No Link')
                ])
        print(f"\nSUCCESS: Export complete!")
        print(f"You can now open '{filename}' in Excel, Google Sheets, or Apple Numbers to review your shared files.")
    except Exception as e:
        print(f"\nERROR: Could not write to CSV file. Ensure you don't already have the file open in another program. Details: {e}")

if __name__ == '__main__':
    print("Starting Shared File Auditing Tool...")
    service = authenticate_google_drive()
    
    if service:
        shared_files = find_shared_files(service)
        export_to_csv(shared_files)
    else:
        print("\nScript aborted due to authentication failure.")
        
    print("Script finished.")