using './main.bicep'

param hubAddressSpace = '10.70.0.0/16'
param logRetentionDays = 90
// sharedKey is passed by the pipeline from Key Vault: az deployment group create ... --parameters sharedKey=$(...)
param sharedKey = readEnvironmentVariable('VPN_SHARED_KEY', '')
