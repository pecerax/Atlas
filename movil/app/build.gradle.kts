plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "cl.atlas.movil"
    compileSdk = 35

    defaultConfig {
        applicationId = "cl.atlas.movil"
        minSdk = 26
        targetSdk = 35
        versionCode = 10
        versionName = "0.10"
    }

    // La llave de firma no vive en el repositorio. Si están estas variables (en GitHub: secretos del repositorio),
    // el APK sale firmado con ella y las versiones siguientes se instalan encima. Sin ellas se usa la llave de
    // depuración de la máquina que compila, y para actualizar hay que desinstalar la versión anterior.
    val almacen = System.getenv("ATLAS_KEYSTORE")
    signingConfigs {
        if (!almacen.isNullOrBlank()) {
            create("atlas") {
                storeFile = file(almacen)
                storePassword = System.getenv("ATLAS_KEYSTORE_CLAVE")
                keyAlias = System.getenv("ATLAS_KEY_ALIAS") ?: "atlas"
                keyPassword = System.getenv("ATLAS_KEY_CLAVE") ?: System.getenv("ATLAS_KEYSTORE_CLAVE")
            }
        }
    }
    buildTypes {
        debug {
            if (!almacen.isNullOrBlank()) signingConfig = signingConfigs.getByName("atlas")
        }
        release {
            isMinifyEnabled = false
            if (!almacen.isNullOrBlank()) signingConfig = signingConfigs.getByName("atlas")
        }
    }
    lint {
        checkReleaseBuilds = false
        abortOnError = false
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
}
