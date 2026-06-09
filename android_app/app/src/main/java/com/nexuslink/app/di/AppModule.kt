package com.nexuslink.app.di

import android.content.Context
import com.nexuslink.app.data.IdentityManager
import com.nexuslink.app.data.PeerStore
import com.nexuslink.app.network.NsdDiscoveryManager
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides
    @Singleton
    fun provideIdentityManager(@ApplicationContext context: Context): IdentityManager {
        return IdentityManager(context)
    }

    @Provides
    @Singleton
    fun providePeerStore(@ApplicationContext context: Context): PeerStore {
        return PeerStore(context)
    }

    @Provides
    @Singleton
    fun provideNsdDiscoveryManager(@ApplicationContext context: Context): NsdDiscoveryManager {
        return NsdDiscoveryManager(context)
    }
}
