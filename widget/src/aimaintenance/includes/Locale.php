<?php declare(strict_types = 1);

namespace Modules\AIMaintenance\Includes;

class Locale {
    private static $translations = [];
    private static $current_locale = 'en_US';
    
    public static function setLocale(string $locale): void {
        self::$current_locale = $locale;
        self::loadTranslations($locale);
    }
    
    public static function t(string $key): string {
        return self::$translations[$key] ?? $key;
    }
    
    private static function loadTranslations(string $locale): void {
        $file = __DIR__ . "/../locale/{$locale}.po";
        
        if (!file_exists($file)) {
            return;
        }
        
        $content = file_get_contents($file);
        $lines = explode("\n", $content);
        
        $msgid = '';
        $msgstr = '';
        $in_msgstr = false;
        
        foreach ($lines as $line) {
            $line = trim($line);
            
            if (strpos($line, 'msgid ') === 0) {
                if ($msgid && $msgstr) {
                    self::$translations[$msgid] = $msgstr;
                }
                $msgid = trim(substr($line, 6), '"');
                $msgstr = '';
                $in_msgstr = false;
            } elseif (strpos($line, 'msgstr ') === 0) {
                $msgstr = trim(substr($line, 7), '"');
                $in_msgstr = true;
            }
        }
        
        if ($msgid && $msgstr) {
            self::$translations[$msgid] = $msgstr;
        }
    }
}