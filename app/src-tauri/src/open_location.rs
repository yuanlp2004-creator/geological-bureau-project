use std::path::{Path, PathBuf};

/// One location for every open dialog, stored with application data, never beside source files.
pub struct OpenLocation {
    preferences: PathBuf,
    directory: Option<PathBuf>,
}

impl OpenLocation {
    pub fn load(data_directory: &Path) -> Self {
        let preferences = data_directory.join("open-file-location.json");
        let directory = std::fs::read(&preferences).ok()
            .and_then(|bytes| serde_json::from_slice::<PathBuf>(&bytes).ok());
        Self { preferences, directory }
    }

    pub fn directory(&self) -> Option<PathBuf> {
        // A moved or disconnected folder should not prevent opening another file.
        self.directory.as_ref().filter(|path| path.is_dir()).cloned()
    }

    pub fn remember(&mut self, selected: Option<&Path>) {
        let Some(path) = selected else { return };
        let Some(directory) = (if path.is_dir() { Some(path) } else { path.parent() }) else { return };
        if !directory.is_dir() { return }
        self.directory = Some(directory.to_path_buf());
        // Preferences are best effort: a read-only profile must not discard a selected file.
        if let Some(parent) = self.preferences.parent() {
            if std::fs::create_dir_all(parent).is_ok() {
                if let Ok(bytes) = serde_json::to_vec(directory) {
                    let _ = std::fs::write(&self.preferences, bytes);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn shares_last_selection_persists_and_keeps_location_on_cancel() {
        let root = std::env::temp_dir().join(format!("geospectrum-open-{}", uuid::Uuid::new_v4()));
        let first = root.join("方法目录甲"); let second = root.join("样品目录乙");
        std::fs::create_dir_all(&first).unwrap(); std::fs::create_dir_all(&second).unwrap();
        let mut state = OpenLocation::load(&root.join("profile"));
        assert_eq!(state.directory(), None);
        state.remember(Some(&first.join("method.mtd")));
        state.remember(Some(&second.join("queue.sam")));
        state.remember(None);
        assert_eq!(state.directory(), Some(second.clone()));
        assert_eq!(OpenLocation::load(&root.join("profile")).directory(), Some(second.clone()));
        std::fs::remove_dir(&second).unwrap();
        assert_eq!(state.directory(), None);
        state.remember(Some(&first));
        assert_eq!(state.directory(), Some(first));
        std::fs::write(root.join("profile/open-file-location.json"), b"broken").unwrap();
        assert_eq!(OpenLocation::load(&root.join("profile")).directory(), None);
        std::fs::remove_dir_all(root).unwrap();
    }
}
