## Changelog

### version 1.3

- made sure that AIodns uses SelectorEventLoop on Windows.
- updated the game search since the SteamUI API has changed.

### Version 1.2

- Made the UI elements resizable with the main window.
- Added minimum size for the main window to ensure the UI remains visible.
- Made the UI more compact by reducing the elements size by 10%.
- Ensured that zip files downloaded from encrypted repositories have the word "encrypted".
- rewrite for the info window with formatted rich text.

### Version 1.1

- Moved the Progress Section to the Right Side.
- Moved the "Download Manifest" Button Beside the "Search" Button.
- Encrypted Repositories Unchecked by Default.
- Added a Warning Label Beside the Info Button.
- Made the Info Window Text Scrollable.
- Added Word Wrap to the Info Window Text.

### Version 1.0 - Initial Release

- Added GitHub repository integration with support for encrypted and decrypted repositories.
- Implemented search functionality to find games by name or AppID using Steam's API.
- Enabled downloading of manifests and `key.vdf` files.
- Automated Lua script generation for SteamTools.
- Provided zip archiving of downloaded files for organized storage.
- Added intuitive UI with features like clipboard paste and toggling repository selections.
- Created robust error handling for user inputs and download processes.
